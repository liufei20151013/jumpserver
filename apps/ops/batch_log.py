# -*- coding: utf-8 -*-
"""
批量任务日志聚合（rsync 物理共享方案）。

多端点并行执行同一批任务时，各端点 worker 只把子任务日志写本地文件，
由内置 log_sync 服务周期执行 rsync 把 `CELERY_LOG_DIR` 镜像到主节点。
本模块在主节点侧负责把已同步到位的子任务日志**后台增量合并**进批量文件：

- `is_subtask_done` / `read_subtask_file`：基于文件尾 magic mark 判定子任务完成并读取；
- `filter_subtask_lines` / `write_batch_header` / `append_batch_block` / `render_summary`：
  过滤冗余内容，以"统一头部 + 各子任务 PLAY 内容(按完成顺序) + 合并后的 Summary"
  的形式流式写入批量日志文件，使回显接近单任务执行时的原始格式；
- `ensure_batch_log`：幂等并入"已完成且未折叠"的子任务（用 Redis set 记录折叠进度），
  全部并入后写结束 magic mark —— 聚合循环可安全地多次调用、增量追加。
"""
import logging
import os
import re

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _

from common.utils.connection import get_redis_client
from .celery.utils import get_celery_task_log_path
from .const import CELERY_LOG_MAGIC_MARK

logger = logging.getLogger(__name__)

# 折叠进度 Redis set 前缀：batch_folded_{batch_id} -> 已并入批量文件的子任务 id 集合
BATCH_FOLDED_PREFIX = 'batch_folded_{batch_id}'

# 行格式: 2026-08-05 10:40:09 消息
TIME_PREFIX_RE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ')
# celery 任务结束行: Task xxx succeeded in x.xxxs: None
CELERY_DONE_RE = re.compile(r'Task .* succeeded in \d+\.\d+s.*')
# Summary 统计键行: - total_assets: 3  /  - Using: 8.45s
SUMMARY_KEY_RE = re.compile(r'^\s*-\s+([A-Za-z_]+):\s*(.*?)\s*$')


def _now_str():
    from common.utils.timezone import local_now
    return local_now().strftime('%Y-%m-%d %H:%M:%S')


def _decode(line):
    if isinstance(line, bytes):
        return line.decode('utf-8', errors='ignore')
    return line


def _strip_time(line):
    return TIME_PREFIX_RE.sub('', line, count=1)


def _folded_key(batch_id):
    return BATCH_FOLDED_PREFIX.format(batch_id=str(batch_id))


def get_batch_log_path(batch_id):
    """批量日志文件路径：与 WS 订阅 batch_id 时推算的路径一致"""
    return get_celery_task_log_path(str(batch_id))


# ---------------- 子任务文件读取与完成判定 ----------------

def is_subtask_done(task_id):
    """
    子任务日志文件是否已同步到位且任务结束。

    判定方式：文件存在且尾部 magic mark 与 `CELERY_LOG_MAGIC_MARK` 一致。
    rsync 以 temp+rename 原子替换整文件，因此"文件尾部即 magic mark"
    这一判定可靠——不会读到写了一半的中间状态。
    """
    log_path = get_celery_task_log_path(str(task_id))
    if not log_path or not os.path.isfile(log_path):
        return False
    mark_len = len(CELERY_LOG_MAGIC_MARK)
    try:
        size = os.path.getsize(log_path)
        if size < mark_len:
            return False
        with open(log_path, 'rb') as f:
            f.seek(-mark_len, os.SEEK_END)
            tail = f.read(mark_len)
        return tail == CELERY_LOG_MAGIC_MARK
    except OSError:
        return False


def read_subtask_file(task_id):
    """读取已同步的子任务日志，返回去除尾部 magic mark 后的行列表"""
    log_path = get_celery_task_log_path(str(task_id))
    if not log_path or not os.path.isfile(log_path):
        return []
    try:
        with open(log_path, 'rb') as f:
            data = f.read()
    except OSError as e:
        logger.warning('Read subtask log %s failed: %s', log_path, e)
        return []
    if data.endswith(CELERY_LOG_MAGIC_MARK):
        data = data[:-len(CELERY_LOG_MAGIC_MARK)]
    text = data.decode('utf-8', errors='ignore')
    return text.splitlines()


# ---------------- 解析 ----------------

def filter_subtask_lines(lines):
    """
    过滤子任务的完整日志行，返回 (play_lines, summary)。

    play_lines: 需写入批量文件的 PLAY 内容(保留原行含时间戳与空行);
    summary:    该子任务 Summary 的统计 dict(total_assets 等数值累加,Using 取最大)。
    """
    play_lines = []
    summary = {}
    in_summary = False
    for raw in lines:
        raw = _decode(raw).rstrip('\r\n')
        msg = _strip_time(raw)
        if msg.startswith('>>>'):
            # 子任务内部头部(任务准备/开始执行/批次)由批量文件统一头部替代
            continue
        if CELERY_DONE_RE.match(msg):
            continue
        if msg.strip() == 'Summary:':
            in_summary = True
            continue
        if in_summary:
            m = SUMMARY_KEY_RE.match(msg)
            if not m:
                continue
            key, value = m.group(1), m.group(2).strip()
            if key == 'Using':
                try:
                    summary[key] = max(summary.get(key, 0.0), float(value.rstrip('s')))
                except ValueError:
                    pass
            else:
                try:
                    summary[key] = summary.get(key, 0) + int(value)
                except ValueError:
                    summary.setdefault(key, value)
            continue
        play_lines.append(raw)
    # 去掉尾部空行,避免块之间双空行
    while play_lines and not play_lines[-1].strip():
        play_lines.pop()
    return play_lines, summary


# ---------------- 渲染与写入 ----------------

def _header_lines():
    with translation.override(settings.LANGUAGE_CODE):
        return [
            _('>>> Task preparation phase'),
            _('>>> Start executing tasks'),
        ]


def write_batch_header(path):
    """
    创建批量日志文件并写入统一头部(幂等)。

    用 O_EXCL 创建,首个请求成功,后续并发请求跳过。
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    try:
        now = _now_str()
        # 末尾不补空行：每个子任务块的 PLAY 内容自带前导空行，避免双空行
        data = '\n'.join('%s %s' % (now, h) for h in _header_lines()) + '\n'
        view = memoryview(data.encode('utf-8', errors='ignore'))
        while view:
            written = os.write(fd, view)
            view = view[written:]
    finally:
        os.close(fd)
    return True


def append_batch_block(path, lines):
    """追加一段日志内容到批量文件(O_APPEND 单次写,避免并发交错)"""
    if not lines:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = ''.join(lines) if lines and lines[0].endswith('\n') else '\n'.join(lines) + '\n'
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        view = memoryview(data.encode('utf-8', errors='ignore'))
        while view:
            written = os.write(fd, view)
            view = view[written:]
    finally:
        os.close(fd)


def render_summary(summaries):
    """
    合并所有子任务 Summary,输出与 BaseManager.print_summary 格式一致的行(每行以 \\n 结尾)。

    total_assets 等数值键累加,Using 取最大(近似整批耗时)。
    """
    merged = {}
    using = 0.0
    for s in summaries:
        if not isinstance(s, dict):
            continue
        for key, value in s.items():
            if key == 'Using':
                try:
                    using = max(using, float(value))
                except (ValueError, TypeError):
                    pass
            elif isinstance(value, int):
                merged[key] = merged.get(key, 0) + value
            elif key not in merged:
                merged[key] = value
    now = _now_str()
    lines = ['\n', '%s Summary:\n' % now]
    # total_assets 优先,与原 print_summary 输出顺序一致
    if 'total_assets' in merged:
        lines.append('%s\t - total_assets: %s\n' % (now, merged.pop('total_assets')))
    for key, value in merged.items():
        lines.append('%s\t - %s: %s\n' % (now, key, value))
    lines.append('%s\t - Using: %ss\n' % (now, using))
    return lines


# ---------------- 增量聚合 ----------------

def ensure_batch_log(batch_id, task_ids, folded_key=None):
    """
    幂等并入"已完成且未折叠"的子任务日志到批量文件（供聚合循环反复调用）。

    - 用 Redis set（folded_key，默认 batch_folded_{batch_id}）记录已并入的子任务，
      多次调用不会重复追加同一子任务块；
    - 每个新完成的子任务：读取文件 → filter_subtask_lines → append_batch_block 追加 PLAY；
    - 全部子任务都并入后：合并 Summary 写结束 magic mark，清理折叠集合。

    Returns:
        (appended_task_ids, batch_done):
            appended_task_ids: 本次新并入的子任务 id 列表;
            batch_done: 全部子任务是否都已并入（此时批量文件已完成，可从活跃集合移除）。
    """
    r = get_redis_client()
    folded_key = folded_key or _folded_key(batch_id)
    task_ids = [str(t) for t in task_ids]
    batch_log_path = get_batch_log_path(batch_id)
    write_batch_header(batch_log_path)

    # 已并入集合（smembers 返回 bytes，统一转 str）
    folded = {_decode(m) for m in (r.smembers(folded_key) or [])}
    appended = []
    for task_id in task_ids:
        if task_id in folded:
            continue
        if not is_subtask_done(task_id):
            continue
        lines = read_subtask_file(task_id)
        play_lines, _summary = filter_subtask_lines(lines)
        append_batch_block(batch_log_path, play_lines)
        r.sadd(folded_key, task_id)
        appended.append(task_id)

    # 全部子任务并入后，合并所有 Summary 并写结束 magic mark
    batch_done = all(t in folded or t in appended for t in task_ids)
    if batch_done:
        summaries = []
        for task_id in task_ids:
            lines = read_subtask_file(task_id)
            _play, summary = filter_subtask_lines(lines)
            summaries.append(summary)
        append_batch_block(batch_log_path, render_summary(summaries))
        with open(batch_log_path, 'ab') as f:
            f.write(CELERY_LOG_MAGIC_MARK)
        try:
            r.delete(folded_key)
        except Exception:
            pass
        logger.info('Batch log %s aggregated: %d subtasks, done', batch_id, len(task_ids))
    else:
        if appended:
            logger.info('Batch log %s aggregated: %s', batch_id, ', '.join(appended))
    return appended, batch_done
