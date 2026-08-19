# ~*~ coding: utf-8 ~*~
import os
import tarfile
import tempfile
import uuid

import requests
from django.conf import settings
from django.utils._os import safe_join

from common.utils import get_logger, make_dirs
from jumpserver.const import PROJECT_DIR
from perms.models import PermNode
from perms.utils import UserPermAssetUtil
from assets.models import Asset, Node

logger = get_logger(__file__)


def get_task_log_path(base_path, task_id, level=2):
    task_id = str(task_id)
    try:
        uuid.UUID(task_id)
    except:
        return os.path.join(PROJECT_DIR, 'data', 'caution.txt')

    rel_path = os.path.join(*task_id[:level], task_id + '.log')
    path = os.path.join(base_path, rel_path)
    make_dirs(os.path.dirname(path), exist_ok=True)
    return path


def get_ansible_log_verbosity(verbosity=0):
    if settings.DEBUG_ANSIBLE:
        return 10
    if verbosity is None and settings.DEBUG:
        return 1
    return verbosity


def merge_nodes_and_assets(nodes, assets, user):
    if not nodes:
        return assets
    perm_util = UserPermAssetUtil(user=user)
    for node_id in nodes:
        if isinstance(node_id, Node):
            node_id = node_id.id
        if node_id == PermNode.FAVORITE_NODE_KEY:
            node_assets = perm_util.get_favorite_assets()
        elif node_id == PermNode.UNGROUPED_NODE_KEY:
            node_assets = perm_util.get_ungroup_assets()
        else:
            node, node_assets = perm_util.get_node_all_assets(node_id)
        assets.extend(node_assets.exclude(id__in=[asset.id for asset in assets]))
    return assets


# ---------------- 端点文件同步（upload 文件 / playbook 剧本按需拉取） ----------------

def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def get_core_url():
    """
    文件同步拉取的主 core 地址。

    使用独立配置 OPS_FILE_SYNC_URL（保存上传源文件的主节点入口）
    （容器内通常为 http://core:8080），拉不到主节点保存的文件。
    未配置时返回空串，调用方应短路跳过拉取（单机 / 共享存储本地已有文件）。
    """
    return (settings.OPS_FILE_SYNC_URL or '').rstrip('/')


def resolve_sync_path(key):
    """
    白名单把 key 解析为本地目录绝对路径。

    仅允许两类：
      - job_upload_file/{job_id}   -> SHARE_DIR/job_upload_file/{job_id}
      - ops/playbook/{playbook_id} -> DATA_DIR/ops/playbook/{playbook_id}
    非法 key 返回 None。
    """
    key = (key or '').strip('/')
    if key.startswith('job_upload_file/'):
        target = key[len('job_upload_file/'):]
        if not _is_uuid(target):
            return None
        return safe_join(settings.SHARE_DIR, 'job_upload_file', target)
    if key.startswith('ops/playbook/'):
        target = key[len('ops/playbook/'):]
        if not _is_uuid(target):
            return None
        return safe_join(settings.DATA_DIR, 'ops', 'playbook', target)
    return None


def _pull_from_core(key, local_path):
    """从主 core 拉取 key 对应目录的 tar 流并解包到本地"""
    core_url = get_core_url()
    if not core_url:
        # 未配置同步源：说明本机/共享存储已能拿到文件，或者多端点未部署，
        # 拉取跳过并返回 False，由调用方决定是否中止任务
        logger.warning(
            'OPS_FILE_SYNC_URL not configured, skip pulling file sync key %s', key
        )
        return False
    url = '{}/api/v1/ops/files/sync/?key={}'.format(core_url, key)
    headers = {'Authorization': 'Token {}'.format(settings.BOOTSTRAP_TOKEN)}
    # 内网 HTTP 同步，忽略 TLS 校验
    resp = requests.get(url, headers=headers, stream=True, timeout=600, verify=False)
    resp.raise_for_status()

    parent = os.path.dirname(local_path)
    os.makedirs(parent, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.tar')
    try:
        with os.fdopen(tmp_fd, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        with tarfile.open(tmp_path, 'r') as tar:
            tar.extractall(parent)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return os.path.isdir(local_path)


def ensure_local_dir(key):
    """
    确保本机存在 key 对应目录；本地缺失时从主 core HTTP 拉取并解包。
    本地已存在且非空则跳过（兼容共享存储与单机部署）。
    """
    local_path = resolve_sync_path(key)
    if not local_path:
        logger.warning('Invalid file sync key: %s', key)
        return False
    if os.path.isdir(local_path) and os.listdir(local_path):
        return True
    try:
        return _pull_from_core(key, local_path)
    except Exception:
        logger.warning('Pull file sync key %s from core failed', key, exc_info=True)
        return False
