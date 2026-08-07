# -*- coding: utf-8 -*-
"""
批量任务日志聚合。

多端点并行执行同一批连通性测试时,每个端点子任务的日志会经 HTTP 增量推送到主节点。
本模块负责:
- 缓冲各子任务推送的日志行(Redis),避免多子任务并发推送在批量文件里交错;
- 过滤子任务内部的冗余内容(>>> 头部、Task succeeded 行、各自独立的 Summary);
- 以"统一头部 + 各子任务 PLAY 内容(按完成顺序) + 合并后的 Summary"的形式
  流式写入批量日志文件,使回显接近单任务执行时的原始格式。
"""
import json
import logging
import os
import re

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

# Redis 缓冲 key 与 TTL
TASK_LOG_BUF_PREFIX = 'task_log_buf_{task_id}'
BATCH_SUMMARIES_PREFIX = 'batch_summaries_{batch_id}'
BUF_TTL = 600

# 行格式: 2026-08-05 10:40:09 消息
TIME_PREFIX_RE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ')
# celery 任务结束行: Task xxx succeeded in x.xxxs: None
CELERY_DONE_RE = re.compile(r'Task .* succeeded in \d+\.\d+s.*')
# Summary 统计键行: - total_assets: 3  /  - Using: 8.45s
SUMMARY_KEY_RE = re.compile(r'^\s*-\s+([A-Za-z_]+):\s*(.*?)\s*$')


def _now_str():
    from common.utils.timezone import local_now
    return local_now().strftime('%Y-%m-%d %H:%M:%S')


def _redis():
    from common.utils.connection import get_redis_client
    return get_redis_client()


def _decode(line):
    if isinstance(line, bytes):
        return line.decode('utf-8', errors='ignore')
    return line


def _strip_time(line):
    return TIME_PREFIX_RE.sub('', line, count=1)


def _task_buf_key(task_id):
    return TASK_LOG_BUF_PREFIX.format(task_id=str(task_id))


def _summaries_key(batch_id):
    return BATCH_SUMMARIES_PREFIX.format(batch_id=str(batch_id))


# ---------------- 缓冲(Redis) ----------------

def buffer_task_lines(task_id, lines):
    """缓冲子任务推送的日志行(含时间戳),用于按子任务去交错"""
    if not lines:
        return
    r = _redis()
    key = _task_buf_key(task_id)
    r.rpush(key, *[_decode(l) for l in lines])
    r.expire(key, BUF_TTL)


def get_task_lines(task_id):
    """取出并清空某子任务的缓冲行"""
    r = _redis()
    key = _task_buf_key(task_id)
    lines = r.lrange(key, 0, -1)
    r.delete(key)
    return [_decode(l) for l in lines]


def stash_subtask_summary(batch_id, summary):
    """保存某个子任务的 Summary 统计,供批完成时合并"""
    if not summary:
        return
    r = _redis()
    key = _summaries_key(batch_id)
    r.rpush(key, json.dumps(summary))
    r.expire(key, BUF_TTL)


def get_subtask_summaries(batch_id):
    """取出并清空该批全部子任务的 Summary 统计"""
    r = _redis()
    key = _summaries_key(batch_id)
    data = r.lrange(key, 0, -1)
    r.delete(key)
    summaries = []
    for d in data:
        try:
            summaries.append(json.loads(_decode(d)))
        except (ValueError, TypeError):
            pass
    return summaries


# ---------------- 解析 ----------------

def filter_subtask_lines(lines):
    """
    过滤子任务的完整日志行,返回 (play_lines, summary)。

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


def append_batch_block(path, play_lines):
    """追加一个子任务的 PLAY 内容(O_APPEND 单次写,避免并发交错)"""
    if not play_lines:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = '\n'.join(play_lines) + '\n'
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
