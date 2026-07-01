from common.utils.connection import get_redis_client

# 锁key常量
CMDB_FULL_SYNC_LOCK_KEY = "lock:cmdb:full_sync_running"
CMDB_INCREMENTAL_SYNC_LOCK_KEY = "lock:cmdb:incremental_sync_running"
# 锁超时时间（秒），防止死锁，大于单次同步最大耗时
LOCK_EXPIRE_SECONDS = 7200

redis_client = get_redis_client()

def acquire_sync_lock() -> bool:
    """获取CMDB同步互斥锁"""
    return redis_client.set(
        name=CMDB_FULL_SYNC_LOCK_KEY,
        value="running",
        ex=LOCK_EXPIRE_SECONDS,
        nx=True  # nx=True 不存在才设置，实现互斥
    )

def release_sync_lock():
    """释放锁"""
    redis_client.delete(CMDB_FULL_SYNC_LOCK_KEY)

def is_sync_locked() -> bool:
    """判断是否有同步任务正在运行"""
    return redis_client.exists(CMDB_FULL_SYNC_LOCK_KEY) == 1

def full_sync_is_running() -> bool:
    return redis_client.exists(CMDB_FULL_SYNC_LOCK_KEY) == 1

def acquire_incr_lock():
    return redis_client.set(
        name=CMDB_INCREMENTAL_SYNC_LOCK_KEY,
        value="running",
        ex=LOCK_EXPIRE_SECONDS,
        nx=True  # nx=True 不存在才设置，实现互斥
    )

def release_incr_lock():
    redis_client.delete(CMDB_INCREMENTAL_SYNC_LOCK_KEY)

def incr_sync_is_running() -> bool:
    return redis_client.exists(CMDB_INCREMENTAL_SYNC_LOCK_KEY) == 1
