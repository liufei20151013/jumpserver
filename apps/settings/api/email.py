# -*- coding: utf-8 -*-
#

from smtplib import SMTPSenderRefused

from django.conf import settings
from django.core.mail import send_mail
from django.utils.translation import gettext_lazy as _
from rest_framework.views import Response, APIView

from common.tasks import get_email_connection as get_connection
from common.utils import get_logger
from common.utils.endpoint_routing import is_master_node
from .. import serializers

logger = get_logger(__file__)

__all__ = ['MailTestingAPI']


class MailTestingAPI(APIView):
    serializer_class = serializers.MailTestSerializer
    success_message = _("Test mail sent to {}, please check")
    rbac_perms = {
        'POST': 'settings.change_email'
    }

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 测试邮件时，邮件服务器信息从配置中获取
        email_host = settings.EMAIL_HOST
        email_port = settings.EMAIL_PORT
        email_host_user = settings.EMAIL_HOST_USER
        email_host_password = settings.EMAIL_HOST_PASSWORD
        email_from = serializer.validated_data.get('EMAIL_FROM')
        email_use_ssl = settings.EMAIL_USE_SSL
        email_use_tls = settings.EMAIL_USE_TLS
        email_recipient = serializer.validated_data.get('EMAIL_RECIPIENT')
        email_from = email_from or email_host_user
        email_recipient = email_recipient or email_from

        if not is_master_node():
            # 多节点部署：非主节点把测试邮件转发到主节点 email 队列发送，
            # 同步等待结果回给前端（用户无感，分布式节点无需开放 SMTP 出网）。
            from common.tasks import send_test_mail_async
            task_kwargs = {
                'host': email_host,
                'port': email_port,
                'username': email_host_user,
                'password': email_host_password,
                'use_tls': email_use_tls,
                'use_ssl': email_use_ssl,
            }
            result = send_test_mail_async.apply_async(
                args=(email_from, email_recipient), kwargs=task_kwargs,
                queue=settings.EMAIL_QUEUE,
            )
            try:
                send_result = result.get(timeout=60) or {}
            except Exception as e:
                logger.error(e)
                return Response(
                    {"error": _('主节点邮件服务暂时不可用，请稍后重试')}, status=400
                )
            if not send_result.get('ok'):
                return Response({"error": send_result.get('error', '')}, status=400)
            return Response({"msg": self.success_message.format(email_recipient)})

        try:
            subject = settings.EMAIL_SUBJECT_PREFIX or '' + "Test"
            message = _("Test smtp setting")
            connection = get_connection(
                host=email_host, port=email_port,
                username=email_host_user, password=email_host_password,
                use_tls=email_use_tls, use_ssl=email_use_ssl,
            )
            send_mail(
                subject, message, email_from, [email_recipient],
                connection=connection
            )
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
            return Response({"error": str(error)}, status=400)
        except Exception as e:
            logger.error(e)
            return Response({"error": str(e)}, status=400)
        return Response({"msg": self.success_message.format(email_recipient)})
