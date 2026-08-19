# -*- coding: utf-8 -*-
import logging
import os
import socket
import uuid
from collections import defaultdict

from django.core.cache import cache

from common.utils.connection import get_redis_client
from common.utils.ip import contains_ip

logger = logging.getLogger(__name__)

# 分发时生成 batch_id 就 sadd 进去；主节点聚合循环按该集合逐个完成聚合后 srem。
# 注意：必须用 get_redis_client()（raw redis client）做 Set 操作——
# django-redis 的 cache 接口不暴露 sadd/smembers/srem，cache.sadd 会抛 AttributeError。
BATCH_ACTIVE_SET_KEY = 'log_sync_active_batches'


# 父-子执行模型中"子执行 id"集合（Redis Set），用于 Job 列表隐藏子执行记录。
#   - batch_tasks_{父id} = [子执行id, ...]（复用日志聚合）
#   - task_batch_{子id} = 父id（复用日志聚合）
#   - job_child_executions = {子执行id, ...}（本集合，供 get_queryset 排除子执行）
CHILD_EXECUTIONS_SET = 'job_child_executions'


def mark_child_executions(child_ids):
    """登记子执行 id 到集合，供 Job 列表隐藏子执行"""
    if not child_ids:
        return
    try:
        get_redis_client().sadd(CHILD_EXECUTIONS_SET, *[str(i) for i in child_ids])
    except Exception:
        logger.exception('Failed to mark child executions %s', child_ids)


def get_child_execution_ids():
    """获取所有子执行 id（Job 列表隐藏用）"""
    try:
        members = get_redis_client().smembers(CHILD_EXECUTIONS_SET) or []
        return [m.decode('utf-8') if isinstance(m, bytes) else str(m) for m in members]
    except Exception:
        logger.exception('Failed to fetch child execution ids')
        return []


def prune_child_execution_ids():
    """清理集合中已不在 DB 的子执行 id（随执行记录清理任务周期调用）"""
    try:
        from ops.models import JobExecution
        r = get_redis_client()
        members = r.smembers(CHILD_EXECUTIONS_SET) or []
        if not members:
            return
        ids = [m.decode('utf-8') if isinstance(m, bytes) else str(m) for m in members]
        existing = {
            str(i) for i in JobExecution.objects.filter(id__in=ids).values_list('id', flat=True)
        }
        stale = [i for i in ids if i not in existing]
        if stale:
            r.srem(CHILD_EXECUTIONS_SET, *stale)
            logger.info('Pruned %d stale child execution ids', len(stale))
    except Exception:
        logger.exception('Failed to prune child execution ids')


def mark_batch_active(batch_id):
    """登记一个待聚合的批量任务，供主节点 log_sync 服务聚合循环扫描"""
    try:
        get_redis_client().sadd(BATCH_ACTIVE_SET_KEY, str(batch_id))
    except Exception:
        logger.exception('Failed to mark batch %s active', batch_id)


def get_active_batch_ids():
    """获取当前待聚合的批量任务 id 列表（聚合循环扫描用）"""
    try:
        return [b.decode('utf-8') if isinstance(b, bytes) else b
                for b in (get_redis_client().smembers(BATCH_ACTIVE_SET_KEY) or [])]
    except Exception:
        logger.exception('Failed to fetch active batches')
        return []


def remove_active_batch(batch_id):
    """批量任务聚合完成后从活跃集合移除"""
    try:
        get_redis_client().srem(BATCH_ACTIVE_SET_KEY, str(batch_id))
    except Exception:
        pass


def is_endpoint_routing_enabled():
    """
    自动检测端点路由是否应启用。

    条件：存在活跃的非默认 Endpoint，且满足以下任一：
    1. 存在活跃的 EndpointRule（IP 规则方式）
    2. 存在配置了 `endpoint` 标签的资产（标签方式，作为 IP 规则的补充）
    """
    try:
        from terminal.models import Endpoint, EndpointRule
        has_endpoints = Endpoint.objects.filter(
            is_active=True
        ).exclude(id=Endpoint.default_id).exists()
        if not has_endpoints:
            return False
        if EndpointRule.objects.filter(is_active=True).exists():
            return True
        # 无规则时：只要存在资产配置了 endpoint 标签也启用路由（标签方式）
        from assets.models import Asset
        from django.contrib.contenttypes.models import ContentType
        from labels.models import LabeledResource
        res_type = ContentType.objects.get_for_model(Asset)
        return LabeledResource.objects.filter(
            res_type=res_type, label__name='endpoint'
        ).exists()
    except Exception:
        return False


def _get_local_ips():
    """获取本机所有 IP 地址"""
    hostname = socket.gethostname()
    ips = set()
    try:
        ips.add(socket.gethostbyname(hostname))
    except socket.gaierror:
        ips.add('127.0.0.1')
    # 获取所有网卡的 IP
    try:
        for info in socket.getaddrinfo(hostname, None):
            ips.add(info[4][0])
    except (socket.gaierror, OSError):
        pass
    return ips


def _resolve_host_to_ips(host):
    """将域名或主机名解析为 IP 地址集合"""
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, OSError):
        return set()


def detect_local_endpoint():
    """
    通过本机 Terminal 组件自动识别本节点对应的 Endpoint。

    匹配方式（按优先级）：
    1. 环境变量 JMS_ENDPOINT_NAME 显式指定（多节点 / VIP / 负载均衡等复杂拓扑下最可靠）
    2. 本机 IP 直接匹配 Endpoint.host（IP 场景）
    3. Endpoint.host 为域名时，DNS 解析后比较 IP

    返回 Endpoint 对象或 None。
    """
    try:
        from terminal.models import Terminal, Endpoint
    except ImportError:
        return None

    local_ips = _get_local_ips()

    # 方式 1: 环境变量显式指定端点名（管理员配置，与 hostname / 网络拓扑无关）
    # 多端点部署时由编排系统为每个节点注入 JMS_ENDPOINT_NAME=<端点名>，
    # 适用于 Endpoint.host 为 VIP / 负载均衡域名等无法解析到本机的场景。
    endpoint_name = os.environ.get('JMS_ENDPOINT_NAME', '').strip()
    if endpoint_name:
        endpoint = Endpoint.objects.filter(
            name=endpoint_name, is_active=True
        ).exclude(id=Endpoint.default_id).first()
        if endpoint:
            return endpoint
        logger.warning(
            f'JMS_ENDPOINT_NAME={endpoint_name} 未匹配到活跃的非默认 Endpoint，'
            f'回退到 IP 自动匹配'
        )

    # 确认本机有注册的 Terminal 组件
    local_terminals = Terminal.objects.filter(
        remote_addr__in=local_ips, is_deleted=False
    )

    # 方式 2: 本机 IP 直接匹配 Endpoint.host
    endpoint = Endpoint.objects.filter(
        host__in=local_ips, is_active=True
    ).exclude(id=Endpoint.default_id).first()
    if endpoint:
        return endpoint

    # 方式 3: Endpoint.host 为域名 → DNS 解析后比较 IP
    # 仅在本机有 Terminal 注册时尝试，避免无意义的 DNS 查询
    if local_terminals.exists():
        for ep in Endpoint.objects.filter(
            is_active=True
        ).exclude(id=Endpoint.default_id).exclude(host=''):
            ep_ips = _resolve_host_to_ips(ep.host)
            if local_ips & ep_ips:
                return ep

    return None


def detect_local_queue():
    """
    获取本节点 Celery Worker 应监听的队列名。
    未匹配到 Endpoint 时返回默认的 'ansible'。
    """
    endpoint = detect_local_endpoint()
    if endpoint:
        queue = endpoint_to_queue_name(endpoint)
        logger.info(
            f"Detected local endpoint: {endpoint.name} "
            f"(host={endpoint.host}), queue={queue}"
        )
        return queue
    return 'ansible'


def endpoint_to_queue_name(endpoint):
    """将 Endpoint 名称转为 Celery 队列名"""
    safe_name = endpoint.name.lower().replace(' ', '_').replace('-', '_')
    return f'ansible_endpoint_{safe_name}'


def resolve_endpoint_for_asset(asset):
    """
    根据资产标签(endpoint)或端点规则确定资产属于哪个 Endpoint。
    标签匹配优先（IP 段可能冲突），无标签匹配时回退到 IP 规则。
    返回 Endpoint 对象或 None（无匹配时）。
    """
    from terminal.models import Endpoint, EndpointRule

    # 方式 1: 资产标签 endpoint 指定端点（优先）
    endpoint = Endpoint.match_by_instance_label(asset, 'ssh')
    if endpoint and not endpoint.is_default():
        return endpoint

    # 方式 2: IP 规则匹配（补充）
    rule = EndpointRule.match(asset, asset.address or '', 'ssh')
    if rule and rule.endpoint and not rule.endpoint.is_default():
        return rule.endpoint
    return None


def resolve_queue_for_asset(asset):
    """获取资产对应的 Celery 队列名，无匹配返回 'ansible'"""
    if not is_endpoint_routing_enabled():
        return 'ansible'
    endpoint = resolve_endpoint_for_asset(asset)
    if endpoint:
        return endpoint_to_queue_name(endpoint)
    return 'ansible'


def _resolve_queues_for_assets(assets):
    """
    批量解析一组资产对应的队列名，返回 {asset_id(str): queue_name}。

    优先级与 `resolve_endpoint_for_asset` 一致：
    资产标签 `endpoint`(= 端点名) 优先，IP 规则兜底；
    均未匹配的资产归入默认 `ansible` 队列。

    批量实现避免 N+1 查询：
    1. 一次查询所有资产的 endpoint 标签
    2. 一次查询所有活跃非默认 Endpoint
    3. 一次查询所有活跃规则，在内存中做 IP 匹配

    调用方需先确认路由已启用（is_endpoint_routing_enabled）。
    """
    from assets.models import Asset
    from django.contrib.contenttypes.models import ContentType
    from terminal.models import Endpoint, EndpointRule
    from labels.models import LabeledResource

    asset_map = {str(a.id): a for a in assets}
    if not asset_map:
        return {}
    asset_ids = list(asset_map)

    # 1) 批量读取资产的 endpoint 标签：{asset_id: [endpoint_name, ...]}
    res_type = ContentType.objects.get_for_model(Asset)
    tag_asset_map = defaultdict(list)
    for row in LabeledResource.objects.filter(
        res_type=res_type, label__name='endpoint', res_id__in=asset_ids,
    ).values('res_id', 'label__value'):
        tag_asset_map[str(row['res_id'])].append(row['label__value'])

    # 2) 活跃非默认端点按名称索引（Endpoint.name 唯一）
    endpoints_by_name = {
        ep.name: ep
        for ep in Endpoint.objects.filter(is_active=True)
        .exclude(id=Endpoint.default_id)
    }

    # 3) 活跃规则（仅含活跃非默认端点），排序与 EndpointRule.match 一致
    rules = list(
        EndpointRule.objects.filter(
            is_active=True, endpoint__is_active=True,
        ).exclude(endpoint=None).exclude(endpoint__id=Endpoint.default_id)
        .order_by('priority', 'is_active', 'name')
    )

    queues = {}
    for asset_id, asset in asset_map.items():
        queue = None

        # 方式 1: 资产标签指定端点（优先，IP 段可能冲突）
        # 多个标签命中多个端点时，取 date_updated 最新的（与 match_by_instance_label 一致）
        label_endpoint = None
        for ep_name in tag_asset_map.get(asset_id, []):
            endpoint = endpoints_by_name.get(ep_name)
            if endpoint and endpoint.is_valid_for(asset, 'ssh'):
                if label_endpoint is None or endpoint.date_updated > label_endpoint.date_updated:
                    label_endpoint = endpoint
        if label_endpoint:
            queue = endpoint_to_queue_name(label_endpoint)

        # 方式 2: IP 规则兜底
        if queue is None:
            target_ip = asset.address or ''
            for rule in rules:
                if not contains_ip(target_ip, rule.ip_group):
                    continue
                if rule.endpoint.is_valid_for(asset, 'ssh'):
                    queue = endpoint_to_queue_name(rule.endpoint)
                    break

        queues[asset_id] = queue or 'ansible'
    return queues


def get_all_endpoint_queues():
    """获取所有活跃非默认 Endpoint 对应的队列名列表"""
    try:
        from terminal.models import Endpoint
        endpoints = Endpoint.objects.filter(
            is_active=True
        ).exclude(id=Endpoint.default_id)
        return [endpoint_to_queue_name(ep) for ep in endpoints]
    except Exception:
        return []


def split_assets_by_endpoint(asset_ids):
    """
    将资产 ID 列表按端点规则分组。

    返回:
        dict: {queue_name: [asset_id, ...], ...}

    路由未启用时返回 {'ansible': asset_ids}。

    解析优先级：资产标签 `endpoint`(= 端点名) 优先，IP 规则兜底，
    与 `resolve_endpoint_for_asset()` 保持一致；未匹配的资产归入默认队列。
    """
    if not is_endpoint_routing_enabled():
        return {'ansible': list(asset_ids)}

    from assets.models import Asset
    assets = Asset.objects.filter(id__in=asset_ids)
    queues = _resolve_queues_for_assets(assets)

    result = defaultdict(list)
    for aid in asset_ids:
        queue = queues.get(str(aid), 'ansible')
        result[queue].append(str(aid))
    return dict(result)


def dispatch_task_to_endpoints(task_func, asset_ids, extra_args=None,
                                extra_kwargs=None):
    """
    按端点规则拆分资产并分发任务到对应队列。

    路由未启用时等价于 task_func.delay(asset_ids, *extra_args, **extra_kwargs)。

    当有多个端点时，生成 batch_id 并建立 task_id -> batch_id 映射，
    供主节点 log_sync 服务聚合所有子任务的日志。

    Args:
        task_func: Celery 任务函数
        asset_ids: 资产 ID 列表
        extra_args: 额外的位置参数
        extra_kwargs: 额外的关键字参数

    Returns:
        list: AsyncResult 列表（每个域一个）
    """
    if not is_endpoint_routing_enabled():
        args = [asset_ids] + (extra_args or [])
        result = task_func.delay(*args, **(extra_kwargs or {}))
        return [result]

    groups = split_assets_by_endpoint(asset_ids)
    results = []
    batch_id = None

    # 多端点时生成 batch_id 用于日志聚合
    if len(groups) > 1:
        batch_id = str(uuid.uuid4())

    for queue, domain_asset_ids in groups.items():
        if not domain_asset_ids:
            continue
        args = [domain_asset_ids] + (extra_args or [])
        kwargs = dict(extra_kwargs or {})
        # 注意：不能把 batch_id 以 kwargs 传给任务 —— apply_async 会按任务签名校验参数，
        # 任务不接受 _batch_id 会抛 TypeError 导致请求 500。
        # 批量聚合依赖下面的 cache 映射（log_sync 服务从 Redis 读取 batch_tasks_{batch_id}）。
        result = task_func.apply_async(
            args=args,
            kwargs=kwargs,
            queue=queue,
        )
        results.append(result)
        logger.info(
            f"Dispatched {task_func.name} to queue={queue} "
            f"with {len(domain_asset_ids)} assets"
        )

        # 建立 task_id -> batch_id 映射，供前端回显 batch_id 使用
        if batch_id:
            cache.set(f'task_batch_{result.id}', batch_id, 3600)

    # 存储 batch_id -> task_ids 映射，供 WebSocket 批量判定 + log_sync 聚合循环
    if batch_id and len(results) > 1:
        task_ids = [r.id for r in results]
        cache.set(f'batch_tasks_{batch_id}', task_ids, 3600)
        mark_batch_active(batch_id)

    return results


def dispatch_task_to_endpoints_for_accounts(task_func, account_ids,
                                             extra_args=None,
                                             extra_kwargs=None):
    """
    按账号所属资产的端点规则分发任务。

    当有多个端点时，生成 batch_id 并建立 task_id -> batch_id 映射。

    Args:
        task_func: Celery 任务函数
        account_ids: 账号 ID 列表
        extra_args: 额外的位置参数
        extra_kwargs: 额外的关键字参数

    Returns:
        list: AsyncResult 列表
    """
    if not is_endpoint_routing_enabled():
        args = [account_ids] + (extra_args or [])
        result = task_func.delay(*args, **(extra_kwargs or {}))
        return [result]

    from accounts.models import Account
    queue_accounts = defaultdict(list)
    accounts = Account.objects.filter(
        id__in=account_ids
    ).select_related('asset')

    # 批量解析账号所属资产对应的队列，避免逐账号查询
    assets = [account.asset for account in accounts if account.asset]
    queues = _resolve_queues_for_assets(assets)

    for account in accounts:
        queue = queues.get(str(account.asset_id), 'ansible')
        queue_accounts[queue].append(str(account.id))

    results = []
    batch_id = None

    # 多端点时生成 batch_id 用于日志聚合
    if len(queue_accounts) > 1:
        batch_id = str(uuid.uuid4())

    for queue, ids in queue_accounts.items():
        if not ids:
            continue
        args = [ids] + (extra_args or [])
        kwargs = dict(extra_kwargs or {})
        # 同 dispatch_task_to_endpoints：不能把 batch_id 作为 kwargs 传给任务，
        # 任务签名不接受该参数会触发 apply_async 参数校验导致 500。
        result = task_func.apply_async(
            args=args,
            kwargs=kwargs,
            queue=queue,
        )
        results.append(result)
        logger.info(
            f"Dispatched {task_func.name} to queue={queue} "
            f"with {len(ids)} accounts"
        )

        # 建立 task_id -> batch_id 映射
        if batch_id:
            cache.set(f'task_batch_{result.id}', batch_id, 3600)

    # 存储 batch_id -> task_ids 映射
    if batch_id and len(results) > 1:
        task_ids = [r.id for r in results]
        cache.set(f'batch_tasks_{batch_id}', task_ids, 3600)
        mark_batch_active(batch_id)

    return results
