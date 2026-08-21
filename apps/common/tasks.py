import os

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives, get_connection
from django.utils.translation import gettext_lazy as _

from common.storage import jms_storage
from common.utils.endpoint_routing import is_master_node
from users.models import User
from .utils import get_logger

logger = get_logger(__file__)


def get_email_connection(**kwargs):
    email_backend_map = {
        'smtp': 'django.core.mail.backends.smtp.EmailBackend',
        'exchange': 'jumpserver.rewriting.exchange.EmailBackend'
    }
    return get_connection(
        backend=email_backend_map.get(settings.EMAIL_PROTOCOL), **kwargs
    )


def task_activity_callback(self, subject, message, recipient_list, *args, **kwargs):
    from users.models import User
    email_list = recipient_list
    resource_ids = list(User.objects.filter(email__in=email_list).values_list('id', flat=True))
    return resource_ids,


@shared_task(
    verbose_name=_("Send email"),
    activity_callback=task_activity_callback,
    description=_(
        "This task will be executed when sending email notifications"
    )
)
def send_mail_async(*args, **kwargs):
    """ Using celery to send email async

    You can use it as django send_mail function

    Example:
    send_mail_sync.delay(subject, message, from_mail, recipient_list, fail_silently=False, html_message=None)

    Also, you can ignore the from_mail, unlike django send_mail, from_email is not a required args:

    Example:
    send_mail_sync.delay(subject, message, recipient_list, fail_silently=False, html_message=None)
    """
    # 多节点部署：仅主节点实际发送 SMTP。非主节点进程内调用时
    # （含 Email backend 同步调用、自动化/备份任务内同步调用），
    # 把任务转发到主节点专属 email 队列，由主节点 worker 执行发送。
    redirected = kwargs.pop('_redirected', False)
    if not is_master_node() and not redirected:
        kwargs['_redirected'] = True
        return send_mail_async.apply_async(
            args=args, kwargs=kwargs, queue=settings.EMAIL_QUEUE
        )

    from users.utils import activate_user_language

    if len(args) == 3:
        args = list(args)
        args[0] = (settings.EMAIL_SUBJECT_PREFIX or '') + args[0]
        from_email = settings.EMAIL_FROM or settings.EMAIL_HOST_USER
        args.insert(2, from_email)

    args = tuple(args)

    subject = args[0] if len(args) > 0 else kwargs.get('subject')
    recipient_list = args[3] if len(args) > 3 else kwargs.get('recipient_list')
    logger.info(
        "send_mail_async called with subject=%r, recipients=%r", subject, recipient_list
    )

    users = User.objects.filter(email__in=recipient_list).all()
    for user in users:
        try:
            with activate_user_language(user):
                send_mail(connection=get_email_connection(), *args, **kwargs)
        except Exception as e:
            logger.error(f"Sending mail to {user.email} error: {e}")


@shared_task(
    verbose_name=_("Send email attachment"),
    activity_callback=task_activity_callback,
    description=_(
        """When an account password is changed or an account backup generates attachments, 
        this task needs to be executed for sending emails and handling attachments"""
    )
)
def send_mail_attachment_async(subject, message, recipient_list, attachment_list=None, **kwargs):
    # 多节点部署：非主节点转发到主节点 email 队列。附件是本节点本地文件
    # （PROJECT_DIR/tmp），主节点读不到，把内容 bytes 随任务带走，主节点落临时文件后发送。
    redirected = kwargs.pop('_redirected', False)
    if not is_master_node() and not redirected:
        attachment_data = []
        for path in (attachment_list or []):
            try:
                with open(path, 'rb') as f:
                    attachment_data.append((os.path.basename(path), f.read()))
            except OSError as e:
                logger.error('Failed to read attachment %s: %s', path, e)
        for path in (attachment_list or []):
            try:
                os.remove(path)
            except OSError:
                pass
        kwargs['_redirected'] = True
        kwargs['attachment_data'] = attachment_data
        return send_mail_attachment_async.apply_async(
            args=(subject, message, recipient_list), kwargs=kwargs,
            queue=settings.EMAIL_QUEUE,
        )

    attachment_data = kwargs.pop('attachment_data', None)
    if attachment_data:
        import tempfile
        attachment_list = list(attachment_list or [])
        for filename, content in attachment_data:
            tmp = os.path.join(tempfile.gettempdir(), filename)
            with open(tmp, 'wb') as f:
                f.write(content)
            attachment_list.append(tmp)

    if attachment_list is None:
        attachment_list = []
    html_message = kwargs.get('html_message')
    from_email = settings.EMAIL_FROM or settings.EMAIL_HOST_USER
    subject = (settings.EMAIL_SUBJECT_PREFIX or '') + subject
    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=from_email,
        to=recipient_list,
        connection=get_email_connection(),
    )
    if html_message:
        email.attach_alternative(html_message, "text/html")
    for attachment in attachment_list:
        email.attach_file(attachment)
        os.remove(attachment)
    return email.send()


@shared_task(
    verbose_name=_('Upload account backup to external storage'),
    description=_(
        "When performing an account backup, this task needs to be executed to external storage (SFTP)"
    )
)
def upload_backup_to_obj_storage(recipient, upload_file):
    logger.info(f'Start upload file : {upload_file}')
    remote_path = os.path.join('account_backup', os.path.basename(upload_file))
    storage = jms_storage.get_object_storage(recipient.config)
    ok, err = storage.upload(src=upload_file, target=remote_path)
    if not ok:
        logger.error(f'upload {upload_file} failed, error: {err}')
        return
    try:
        os.remove(upload_file)
    except Exception as e:
        print(f'remove upload file : {upload_file} error: {e}')


@shared_task(
    verbose_name=_("Send test email"),
    description=_(
        "SMTP 配置测试邮件（通知设置\"测试连接\"）：分布式节点经 email 队列转发到主节点发送"
    )
)
def send_test_mail_async(email_from, email_recipient, **kwargs):
    """SMTP 测试邮件（邮箱配置"测试连接"用）。多节点部署下统一由主节点发送。

    非主节点 web 进程把请求转发到主节点 email 队列，本任务在主节点 worker 执行，
    返回 {'ok': bool, 'error': str}，请求节点同步等待结果回给前端（用户无感）。
    """
    # 兜底：万一任务被非主节点 worker 执行，转发回主节点 email 队列（_redirected 防死循环）
    redirected = kwargs.pop('_redirected', False)
    if not is_master_node() and not redirected:
        kwargs['_redirected'] = True
        return send_test_mail_async.apply_async(
            args=(email_from, email_recipient), kwargs=kwargs,
            queue=settings.EMAIL_QUEUE,
        )

    from smtplib import SMTPSenderRefused
    from django.core.mail import send_mail
    from django.utils.translation import gettext_lazy as _

    try:
        subject = (settings.EMAIL_SUBJECT_PREFIX or '') + "Test"
        message = _("Test smtp setting")
        email_from = email_from or settings.EMAIL_HOST_USER
        email_recipient = email_recipient or email_from
        connection = get_email_connection(
            host=kwargs.get('host') or settings.EMAIL_HOST,
            port=kwargs.get('port') or settings.EMAIL_PORT,
            username=kwargs.get('username') or settings.EMAIL_HOST_USER,
            password=kwargs.get('password') or settings.EMAIL_HOST_PASSWORD,
            use_tls=kwargs.get('use_tls', settings.EMAIL_USE_TLS),
            use_ssl=kwargs.get('use_ssl', settings.EMAIL_USE_SSL),
        )
        send_mail(
            subject, message, email_from, [email_recipient],
            connection=connection,
        )
        return {'ok': True, 'error': ''}
    except SMTPSenderRefused as e:
        error = e.smtp_error
        if isinstance(error, bytes):
            for coding in ('gbk', 'utf8'):
                try:
                    error = error.decode(coding)
                except UnicodeDecodeError:
                    continue
                else:
                    break
        return {'ok': False, 'error': str(error)}
    except Exception as e:
        logger.error(e)
        return {'ok': False, 'error': str(e)}
