import io
import json
import unittest
from unittest.mock import Mock

from origin_pro_mcp.worker_process import ProcessSession
from origin_pro_mcp.daemon import Pool


class WorkerProtocolTests(unittest.TestCase):
    def test_ready_identity_and_success_result_are_forwarded(self):
        worker = ProcessSession('test')
        frames = [
            {'kind': 'ready', 'pid': 42, 'worker_pid': 12,
             'identity': {'pid': 42, 'image': 'Origin64.exe', 'creation_filetime': 9}},
            {'kind': 'response', 'response': {'type': 'response', 'request_id': 'r',
                                                'ok': True, 'result': 'ok', 'error': None}},
        ]
        worker._process = Mock(stdout=io.StringIO(''.join(json.dumps(f)+'\n' for f in frames)))
        callback = Mock(); worker._callbacks['r'] = callback
        worker._read()
        self.assertEqual(worker.pid, 42)
        self.assertEqual(worker.worker_pid, 12)
        self.assertEqual(worker.identity['creation_filetime'], 9)
        callback.assert_called_once()
        self.assertTrue(callback.call_args.args[0]['ok'])

    def test_worker_exit_marks_inflight_outcome_unknown(self):
        worker = ProcessSession('test')
        worker._process = Mock(stdout=io.StringIO(''))
        callback = Mock(); worker._callbacks['write'] = callback
        worker._read()
        self.assertTrue(worker._dead)
        self.assertIn('before verifying', worker._error)
        callback.assert_called_once()
        self.assertIn('partial or unknown', callback.call_args.args[0]['error'])

    def test_dead_worker_never_silently_mints_replacement(self):
        pool = Pool(lambda: object(), {})
        dead = ProcessSession('test'); dead._dead = True
        pool._sessions['test'] = dead
        with self.assertRaisesRegex(RuntimeError, 'cannot be reused'):
            pool.acquire('test')
        self.assertIs(pool.get('test'), dead)


if __name__ == '__main__':
    unittest.main()
