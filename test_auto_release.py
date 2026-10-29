import unittest
from unittest.mock import patch

import fishing_macro as macro


class AutoReleaseTests(unittest.TestCase):
    def run_job(self, replies, repeat=1):
        with patch('threading.Thread.start'):
            job = macro.MacroJob(0, '박건', repeat, False)
        with patch.object(job, '_sleep', return_value=False), \
             patch.object(job, '_wait_until_ready', return_value=True), \
             patch.object(job, '_command', return_value=True) as command, \
             patch.object(job, '_await_reply', side_effect=replies), \
             patch.object(macro, 'copy_chat', return_value=''), \
             patch.object(macro, 'release_stuck_keys'):
            job._run()
        self.assertIsNone(job.error)
        return job, [call.args[0] for call in command.call_args_list]

    def test_release_uses_next_cycle_and_success_resets_attempts(self):
        job, commands = self.run_job([
            ('auto',), ('auto',), ('success', 1, 4000, None),
        ])
        self.assertEqual(commands, ['낚시', '수동', '낚시'])
        self.assertEqual((job.done, job.auto_releases, job.end_reason), (1, 0, 'finished'))

    def test_stops_after_three_failed_releases(self):
        job, commands = self.run_job([('auto',), (), ('auto',), (), ('auto',), (), ('auto',)])
        self.assertEqual(commands, ['낚시', '수동', '낚시', '수동', '낚시', '수동', '낚시'])
        self.assertEqual((job.done, job.auto_releases, job.end_reason), (0, 3, 'stuck_auto'))

    def test_success_on_third_attempt_allows_new_episode(self):
        job, commands = self.run_job([
            ('auto',), (), ('auto',), (), ('auto',), (), ('success', 1, 4000, None),
            ('auto',), (), ('success', 2, 4000, None),
        ], repeat=2)
        self.assertEqual(commands.count('수동'), 4)
        self.assertEqual((job.done, job.auto_releases, job.end_reason), (2, 0, 'finished'))

    def test_extra_fishing_success_resets_attempts(self):
        job, commands = self.run_job([('auto',), (), ('extra_success', 1, 1000)])
        self.assertEqual(commands, ['낚시', '수동', '낚시'])
        self.assertEqual((job.done, job.auto_releases, job.end_reason), (1, 0, 'finished'))

    def test_stop_during_manual_reply_does_not_send_more_fishing(self):
        job, commands = self.run_job([('auto',), None])
        self.assertEqual(commands, ['낚시', '수동'])
        self.assertEqual(job.done, 0)


if __name__ == '__main__':
    unittest.main()
