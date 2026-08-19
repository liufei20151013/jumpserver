import os
import tempfile
from unittest import mock

from django.test import TestCase

from ops import batch_log
from ops.const import CELERY_LOG_MAGIC_MARK


class FakeRedis:
    """极简 Redis 客户端桩，支持 ensure_batch_log 用到的 smembers/sadd/delete"""

    def __init__(self):
        self.sets = {}

    def smembers(self, key):
        return {v.encode('utf-8') for v in self.sets.get(key, set())}

    def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    def delete(self, *keys):
        n = 0
        for key in keys:
            if key in self.sets:
                del self.sets[key]
                n += 1
        return n


def write_subtask_file(path, play='Connecting to host ...', total_assets=1,
                       using=1.2, done=True):
    """写一个模拟已同步的子任务日志文件"""
    lines = [
        '2026-08-05 10:00:00 >>> Task preparation phase',
        f'2026-08-05 10:00:01 {play}',
        '2026-08-05 10:00:02 Summary:',
        f'2026-08-05 10:00:02 \t - total_assets: {total_assets}',
        f'2026-08-05 10:00:02 \t - Using: {using}s',
        '2026-08-05 10:00:03 Task test_task succeeded in 1.20s: None',
    ]
    data = '\n'.join(lines).encode('utf-8')
    if done:
        data += CELERY_LOG_MAGIC_MARK
    with open(path, 'wb') as f:
        f.write(data)


class BatchLogTestCase(TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.fake_redis = FakeRedis()
        self.redis_patcher = mock.patch('ops.batch_log.get_redis_client',
                                        return_value=self.fake_redis)
        self.redis_patcher.start()

    def tearDown(self):
        self.redis_patcher.stop()

    def _paths(self, mapping):
        """按 task_id/batch_id 映射到临时文件路径"""
        for key, value in mapping.items():
            mapping[key] = os.path.join(self.tmp_dir, value)
        return mapping

    def test_filter_subtask_lines(self):
        lines = [
            '2026-08-05 10:00:00 >>> Task preparation phase',
            '2026-08-05 10:00:01 Connecting to host ...',
            '2026-08-05 10:00:02 Summary:',
            '2026-08-05 10:00:02 \t - total_assets: 3',
            '2026-08-05 10:00:02 \t - Using: 1.50s',
            '2026-08-05 10:00:03 Task test succeeded in 1.50s: None',
            '',
        ]
        play_lines, summary = batch_log.filter_subtask_lines(lines)
        # 头部 / Summary / 完成行被剔除,仅保留 PLAY 内容
        self.assertEqual(play_lines, ['2026-08-05 10:00:01 Connecting to host ...'])
        self.assertEqual(summary['total_assets'], 3)
        self.assertEqual(summary['Using'], 1.5)

    def test_render_summary(self):
        summaries = [
            {'total_assets': 1, 'ok': 1, 'Using': 1.2},
            {'total_assets': 2, 'ok': 2, 'Using': 2.3},
        ]
        lines = batch_log.render_summary(summaries)
        text = ''.join(lines)
        self.assertIn('Summary:', text)
        self.assertIn('- total_assets: 3', text)
        self.assertIn('- ok: 3', text)
        self.assertIn('- Using: 2.3s', text)

    def test_write_batch_header_idempotent(self):
        path = os.path.join(self.tmp_dir, 'batch.log')
        self.assertTrue(batch_log.write_batch_header(path))
        # 幂等：已存在时返回 False，不覆盖
        self.assertFalse(batch_log.write_batch_header(path))
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('Task preparation', content)
        self.assertIn('Start executing', content)

    def test_is_subtask_done(self):
        done_path = os.path.join(self.tmp_dir, 'done.log')
        write_subtask_file(done_path, done=True)
        undone_path = os.path.join(self.tmp_dir, 'undone.log')
        write_subtask_file(undone_path, done=False)
        missing_path = os.path.join(self.tmp_dir, 'missing.log')

        with mock.patch('ops.batch_log.get_celery_task_log_path',
                        side_effect=lambda tid: {1: done_path, 2: undone_path,
                                                  3: missing_path}[int(tid)]):
            self.assertTrue(batch_log.is_subtask_done(1))
            self.assertFalse(batch_log.is_subtask_done(2))
            self.assertFalse(batch_log.is_subtask_done(3))

    def test_read_subtask_file(self):
        path = os.path.join(self.tmp_dir, 'task.log')
        write_subtask_file(path)
        with mock.patch('ops.batch_log.get_celery_task_log_path',
                        return_value=path):
            lines = batch_log.read_subtask_file('t')
        # magic mark 被剔除，且行列表不带 magic 字节
        self.assertNotIn(CELERY_LOG_MAGIC_MARK, b''.join(
            line.encode('utf-8') for line in lines))
        self.assertTrue(lines[1].startswith('2026-08-05 10:00:01'))

    def test_ensure_batch_log_partial_then_done(self):
        paths = self._paths({
            'a': 'a.log',
            'b': 'b.log',
            'batch': 'batch.log',
        })
        write_subtask_file(paths['a'], play='Connect a')
        # b 尚未完成
        write_subtask_file(paths['b'], play='Connect b', done=False)

        def path_for(task_id):
            return paths.get(str(task_id))

        with mock.patch('ops.batch_log.get_celery_task_log_path',
                        side_effect=path_for):
            # 第一轮：a 完成并入；b 未完成但其已同步内容也实时并入
            appended, done = batch_log.ensure_batch_log('batch', ['a', 'b'])
            self.assertEqual(appended, ['a', 'b'])
            self.assertFalse(done)
            # 只有 a 完成被标记折叠；b 未完成不入折叠集合
            self.assertEqual(
                self.fake_redis.sets.get('batch_folded_batch'), {'a'}
            )

            # b 完成后再聚合一轮
            write_subtask_file(paths['b'], play='Connect b', done=True)
            appended, done = batch_log.ensure_batch_log('batch', ['a', 'b'])
            self.assertEqual(appended, ['b'])
            self.assertTrue(done)
            # 全部并入后折叠集合被清理
            self.assertNotIn('batch_folded_batch', self.fake_redis.sets)

        with open(paths['batch'], 'rb') as f:
            data = f.read()
        # 批量文件以 magic mark 结尾
        self.assertTrue(data.endswith(CELERY_LOG_MAGIC_MARK))
        text = data.decode('utf-8', errors='ignore')
        self.assertIn('Connect a', text)
        self.assertIn('Connect b', text)
        self.assertIn('Summary:', text)
        # total_assets 两个子任务合并
        self.assertIn('- total_assets: 2', text)

    def test_ensure_batch_log_realtime_incremental(self):
        """执行中的子任务日志按偏移增量并入，完成后再写 Summary/magic mark，且不重复"""
        paths = self._paths({'a': 'a.log', 'batch': 'batch.log'})
        path = paths['a']

        def path_for(task_id):
            return paths.get(str(task_id))

        def write_segment(segment='', done=False):
            with open(path, 'ab') as f:
                if segment:
                    f.write(segment.encode('utf-8'))
                if done:
                    f.write(CELERY_LOG_MAGIC_MARK)

        with mock.patch('ops.batch_log.get_celery_task_log_path',
                        side_effect=path_for):
            # ① 执行中：已同步了第一部分（无 magic mark）
            write_segment('2026-08-05 10:00:00 >>> Task preparation phase\n')
            write_segment('2026-08-05 10:00:01 transfer 40%\n')
            appended, done = batch_log.ensure_batch_log('batch', ['a'])
            self.assertIn('a', appended)
            self.assertFalse(done)

            # ② 执行中：追加第二部分（仍未完成）
            write_segment('2026-08-05 10:00:02 transfer 80%\n')
            write_segment('2026-08-05 10:00:03 Summary:\n')
            write_segment('2026-08-05 10:00:03 \t - total_assets: 1\n')
            write_segment('2026-08-05 10:00:03 \t - Using: 1.5s\n')
            appended, done = batch_log.ensure_batch_log('batch', ['a'])
            self.assertFalse(done)

            # ③ 任务完成：写入 magic mark
            write_segment(done=True)
            appended, done = batch_log.ensure_batch_log('batch', ['a'])
            self.assertTrue(done)
            # 完成且全部并入后折叠集合被清理
            self.assertNotIn('batch_folded_batch', self.fake_redis.sets)

        with open(paths['batch'], 'rb') as f:
            data = f.read()
        self.assertTrue(data.endswith(CELERY_LOG_MAGIC_MARK))
        text = data.decode('utf-8', errors='ignore')
        # 执行中内容实时回显，且不重复
        self.assertIn('transfer 40%', text)
        self.assertIn('transfer 80%', text)
        self.assertEqual(text.count('transfer 40%'), 1)
        self.assertEqual(text.count('transfer 80%'), 1)
        # Summary 只出现在最终合并段
        self.assertIn('Summary:', text)
