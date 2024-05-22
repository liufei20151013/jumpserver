# from celery import shared_task
# from django.utils.translation import gettext_lazy as _
# from accounts.tasks import verify_accounts_connectivity_task
# from assets.models import Asset, Platform
# from ops.celery.decorator import after_app_ready_start
# from ops.celery.utils import create_or_update_celery_periodic_tasks
#
# import time
# from accounts.models import Account
# from orgs.models import Organization
# from orgs.utils import set_current_org
# from common.utils import get_logger
# from ops.celery.utils import get_celery_task_log_path
#
# logger = get_logger(__name__)
#
# @shared_task(verbose_name=_('verify all accounts'))
# def verify_all_accounts():
#     verify_accounts()
#
# @shared_task(verbose_name=_('Registration periodic verify all accounts task'))
# @after_app_ready_start
# def verify_all_accounts_periodic():
#     crontab = '27 15 * * *'
#     task_name = 'verify_all_accounts'
#     tasks = {
#         task_name: {
#             'task': verify_all_accounts.name,
#             'interval': None,
#             'crontab': crontab,
#             'enabled': True,
#         }
#     }
#     create_or_update_celery_periodic_tasks(tasks)
#
# def verify_accounts():
#     orgs = Organization.objects.exclude(name='SYSTEM')
#     for org in orgs:
#         set_current_org(org)
#
#         # 查询主机账号
#         platforms = Platform.objects.filter(category='host', name='Gateway')
#         assets = Asset.objects.filter(platform__in=platforms)
#         print('Org:{}, assets size:{}.'.format(org.name, len(assets)))
#         for asset in assets:
#             accounts = Account.objects.filter(asset=asset)
#             if not accounts.exists():
#                 continue
#
#             for account in accounts:
#                 try:
#                     ids = [account.id]
#                     task = verify_accounts_connectivity_task.delay(ids)
#                     print('Verify account[{}], asset[{}], task: {}.'.format(account.name, asset.name, task.id))
#
#                     content = ''
#                     max_retries = 10
#                     retry_count = 0
#                     while retry_count < max_retries:
#                         try:
#                             # 任务下发后，需要一定的执行时间
#                             time.sleep(10)
#
#                             log_path = get_celery_task_log_path(task.id)
#                             print(log_path)
#                             content = read_local_file(log_path)
#
#                             # 测试结束标识
#                             if content.__contains__('Task accounts.tasks.verify_account.verify_accounts_connectivity_task'):
#                                 print(content)
#                                 break
#                         except Exception as e:
#                             retry_count += 1
#                             print(f'Retry {retry_count} times.')
#
#                     if content.__contains__('Unable to connect to asset') or \
#                             content.__contains__('Failed to connect to the host') or \
#                             content.__contains__('无法连接到') or \
#                             content.__contains__('Invalid/incorrect password'):
#                         if content.__contains__('no such'):
#                             print('Do not delete account[{}], asset[{}].'.format(account.name, asset.name))
#                             continue
#
#                         # 处理无效账号
#                         account.delete()
#                         print('Success to delete account[{}], asset[{}].'.format(account.name, asset.name))
#                 except Exception as e:
#                     print('Failed to verify account[{}], asset[{}], error:{}'.format(account.name, asset.name, e))
#
#     print('Success to verify  all accounts.')
#
#
# def read_local_file(file_path):
#     content = ''
#     try:
#         with open(file_path, 'r') as file:
#             content = file.read()
#     except FileNotFoundError:
#         pass
#     return content
