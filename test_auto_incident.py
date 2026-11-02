"""Regression for the 2026-11-02 split between history and control detection."""
import unittest
from unittest.mock import patch

import fishing_macro as m
import test_auto_release
from fishing_history import History, Observer


def line(sender, body):
    return f'[{sender}] [오후 12:28] {body}'


def catch(count):
    return line('나', '@봇 낚시') + '\n' + line('봇', f'@사용자 낚시 성공!\n획득 골드: 10G\n오늘 낚시: {count} / 3000')


class AutoIncidentTests(unittest.TestCase):
    def wait_for(self, baseline, current):
        with patch('threading.Thread.start'):
            job = m.MacroJob(1, '나', 1, False)
        job._last_enter = 0
        job._reply_baseline = baseline
        job._current_command_seen = False
        job.observer.baseline(baseline)
        clock = [0.0]
        def sleep(seconds, watch=False):
            clock[0] += seconds
            return False
        with patch.object(job, '_sleep', side_effect=sleep), \
             patch.object(m.time, 'perf_counter', side_effect=lambda: clock[0]), \
             patch.object(m, 'copy_chat', return_value=current), \
             patch.object(m, 'GetForegroundWindow', return_value=1):
            reply = job._await_reply()
        return job, reply

    def test_auto_record_must_control_cycle_despite_historical_counter_gap(self):
        baseline = '\n'.join(catch(n) for n in (303, 305, 306))
        current = baseline + '\n' + line('나', '@봇 낚시') + '\n' + line('봇', '@사용자 자동어가 다시 나타났어요.')
        # The historical replay assigns the auto to an older unanswered command.
        self.assertIsNone(m.my_replies(current, '나')[-1][1])
        job, reply = self.wait_for(baseline, current)
        self.assertTrue(any(r['kind'] == 'auto' for r in job.observer.history.snapshot()))
        self.assertEqual(reply, ('auto',))

    def test_other_players_auto_does_not_trigger_manual(self):
        baseline = catch(303)
        current = baseline + '\n' + line('친구', '@봇 낚시') + '\n' + line('봇', '@사용자 자동어가 다시 나타났어요.')
        job, reply = self.wait_for(baseline, current)
        self.assertEqual(reply, ())

    def test_unchanged_old_auto_does_not_trigger_manual(self):
        baseline = line('나', '@봇 낚시') + '\n' + line('봇', '@사용자 자동어가 다시 나타났어요.')
        job, reply = self.wait_for(baseline, baseline)
        self.assertEqual(reply, ())

    def test_incident_reply_schedules_manual_before_next_fishing(self):
        baseline = '\n'.join(catch(n) for n in (303, 305, 306))
        current = baseline + '\n' + line('나', '@봇 낚시') + '\n' + line('봇', '@사용자 자동어가 다시 나타났어요.')
        _, reply = self.wait_for(baseline, current)
        job, commands = test_auto_release.AutoReleaseTests().run_job([reply, (), ('success', 307, 3000, None)])
        self.assertEqual(commands, ['낚시', '수동', '낚시'])
        self.assertEqual(job.done, 1)

    def test_silent_manual_does_not_consume_new_auto_signal(self):
        observer = Observer(History(), '나')
        observer.baseline('')
        text = line('나', '@봇 수동') + '\n' + line('나', '@봇 낚시') + '\n' + line('봇', '@사용자 자동어가 다시 나타났어요.')
        observer.observe(text)
        self.assertEqual(observer.auto_version, 1)
        observer.observe(text)
        self.assertEqual(observer.auto_version, 1)


if __name__ == '__main__':
    unittest.main()
