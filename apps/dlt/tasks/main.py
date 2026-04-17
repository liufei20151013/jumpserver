from datetime import datetime
from croniter import croniter
from django.utils import timezone

from dlt.models import DltAccount
from orgs.models import Organization
from django.conf import settings
from rbac.models import Role
from users.models import User


def process_data(isFullSync):
    enabled = settings.DLT_ENABLED
    if not enabled:
        print('当前统一权限同步功能未开启, 不需要处理')
        return

    print("处理同步的数据 Start.")


    if isFullSync:
        accounts = DltAccount.objects.all()
    else:
        last_cron_run_time = get_last_cron_run_time(settings.PAM_INCREMENTAL_DATA_SYNC_CRONTAB)
        accounts = DltAccount.objects.filter(date_updated__gte=last_cron_run_time)

    if accounts.exists():
        for account in accounts:
            try:
                print('dlt account: {}'.format(account))
                org = account.org
                # 需要用户org在堡垒机对应组织的备注里填入org信息   组织 comment ->  用户 org
                org_list = Organization.objects.filter(comment=org)
                if not org_list.exists():
                    print('堡垒机组织未关联用户org: {}'.format(org))
                    continue

                action_type = account.action_type
                is_active = True if account.status == '1' else False
                if action_type in ['Add', 'Modify', 'ParticularChanges']:
                    name = account.cn
                    username = account.uid
                    email = account.email

                    defaults = {
                        "email": email,
                        "name": name,
                        "is_active": is_active,
                        "source": User.Source.oauth2.value,
                    }

                    # 创建或更新用户
                    user, created = User.objects.get_or_create(
                        username=username,
                        defaults=defaults
                    )

                    # 如果用户已存在，更新信息
                    if not created:
                        user.email = email
                        user.name = name
                        user.is_active = is_active
                        user.date_updated = timezone.now()
                        user.save(update_fields=["email", "name", "is_active", "date_updated"])

                    # 更新用户：如果用户更换了组织，是否需要把之前绑定的组织移除掉user.orgs.clear()，再绑定新组织？不建议，原组织绑定了一些授权，最好是手动移除，防止影响用户授权等数据
                    org_role = Role.objects.get(name='OrgUser', scope='org')
                    organization = org_list.first()
                    organization.add_member(user, org_role)
                    print(f"OAuth2 用户创建/更新成功: {account.uid} (新建:{created})")

                elif action_type == 'Enable':
                    users = User.objects.filter(username = account.uid)
                    if users.exists():
                        users.update(is_active=True, date_updated = timezone.now())
                        print(f"OAuth2 用户启用成功: {account.uid}")
                elif action_type in ['Disable', 'Delete', 'ReclaimAccount']:
                    users = User.objects.filter(username=account.uid)
                    if users.exists():
                        users.update(is_active=False, date_updated = timezone.now())
                        print(f"OAuth2 用户禁用成功: {account.uid}")
            except Exception as e:
                print(e)

    print("处理同步的数据 End.")


def get_last_cron_run_time(cron_exp):
    """
    获取上上一次Cron执行时间，返回带时区的字符串格式 %Y-%m-%d %H:%M:%S.%f
    """
    now = datetime.now()
    cron = croniter(cron_exp, now)
    cron.get_prev(datetime)
    last_run_naive = cron.get_prev(datetime)
    tz = timezone.get_current_timezone()
    last_run_aware = timezone.make_aware(last_run_naive, tz)
    return last_run_aware.strftime("%Y-%m-%d %H:%M:%S.%f")
