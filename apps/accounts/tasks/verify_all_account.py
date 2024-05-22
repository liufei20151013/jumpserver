from datetime import datetime

from xlsxwriter import Workbook
from celery import shared_task
from django.utils.translation import gettext_lazy as _
from accounts.tasks import verify_accounts_connectivity_task
from assets.models import Asset, Platform
from ops.celery.decorator import after_app_ready_start
from ops.celery.utils import create_or_update_celery_periodic_tasks

import time
import datetime
from accounts.models import Account
from orgs.models import Organization
from orgs.utils import set_current_org
from common.utils import get_logger
from ops.celery.utils import get_celery_task_log_path

logger = get_logger(__name__)


@shared_task(verbose_name=_('verify all accounts'))
def verify_all_accounts():
    verify_accounts()


@shared_task(verbose_name=_('Registration periodic verify all accounts task'))
@after_app_ready_start
def verify_all_accounts_periodic():
    crontab = '48 17 * * *'
    task_name = 'verify_all_accounts'
    tasks = {
        task_name: {
            'task': verify_all_accounts.name,
            'interval': None,
            'crontab': crontab,
            'enabled': True,
        }
    }
    create_or_update_celery_periodic_tasks(tasks)


def verify_accounts():
    data = []

    orgs = Organization.objects.exclude(name='SYSTEM')
    for org in orgs:
        set_current_org(org)

        # 查询主机账号
        platforms = Platform.objects.filter(category='host')
        assets = Asset.objects.filter(platform__in=platforms)
        print('Org:{}, assets size:{}.'.format(org.name, len(assets)))
        for asset in assets:
            accounts = Account.objects.filter(asset=asset)
            if not accounts.exists():
                continue

            for account in accounts:
                try:
                    ids = [account.id]
                    task = verify_accounts_connectivity_task.delay(ids)
                    print('Verify account[{}], asset[{}], task: {}.'.format(account.name, asset.name, task.id))

                    max_retries = 10
                    retry_count = 0
                    while retry_count < max_retries:
                        try:
                            # 任务下发后，需要一定的执行时间
                            time.sleep(10)

                            log_path = get_celery_task_log_path(task.id)
                            print(log_path)
                            content = read_local_file(log_path)

                            # 测试结束标识
                            if content.__contains__(
                                    'Task accounts.tasks.verify_account.verify_accounts_connectivity_task'):
                                print(content)

                                # 先只打印账号可连接性测试结果
                                data.append({
                                    'account_id': str(account.id),
                                    'account_name': account.name,
                                    'account_username': account.username,
                                    'asset_id': str(asset.id),
                                    'asset_name': asset.name,
                                    'asset_address': asset.address,
                                    'test_result': content
                                })
                                break
                        except Exception as e:
                            retry_count += 1
                            print(f'Retry {retry_count} times.')

                except Exception as e:
                    data.append({
                        'account_id': account.id,
                        'account_name': account.name,
                        'account_username': account.username,
                        'asset_id': asset.id,
                        'asset_name': asset.name,
                        'asset_address': asset.address,
                        'test_result': e
                    })

    export_to_excel(data)
    print('Success to verify  all accounts.')


def read_local_file(file_path):
    content = ''
    try:
        with open(file_path, 'r') as file:
            content = file.read()
    except FileNotFoundError:
        pass
    return content


def export_to_excel(data):
    # 创建一个Excel文件对象
    date_string = datetime.datetime.now().strftime('%Y-%m-%d')
    filename = f'./JumpServer-Accounts-{date_string}.xlsx'
    workbook = Workbook(filename)

    # 添加一个工作表
    worksheet = workbook.add_worksheet("Sheet1")

    # 写入表头
    worksheet.write_string(0, 0, 'account_id')
    worksheet.write_string(0, 1, 'account_name')
    worksheet.write_string(0, 2, 'account_username')
    worksheet.write_string(0, 3, 'asset_id')
    worksheet.write_string(0, 4, 'asset_name')
    worksheet.write_string(0, 5, 'asset_address')
    worksheet.write_string(0, 6, 'test_result')

    for index, item in enumerate(data):
        worksheet.write_string(index + 1, 0, item['account_id'])
        worksheet.write_string(index + 1, 1, item['account_name'])
        worksheet.write_string(index + 1, 2, item['account_username'])
        worksheet.write_string(index + 1, 3, item['asset_id'])
        worksheet.write_string(index + 1, 4, item['asset_name'])
        worksheet.write_string(index + 1, 5, item['asset_address'])
        worksheet.write_string(index + 1, 6, item['test_result'])

    workbook.close()
