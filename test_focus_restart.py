import unittest
from unittest.mock import patch

import fishing_macro as m


class FocusRestartTests(unittest.TestCase):
    def job(self):
        with patch('threading.Thread.start'):
            return m.MacroJob(1, '나', 1, False)

    def test_each_interrupted_input_stage_restarts_same_command(self):
        for command in ('낚시', '수동'):
            for stage in ('type_at', 'select', 'type_command', 'send'):
                with self.subTest(command=command, stage=stage):
                    job = self.job()
                    events = []
                    interrupted = False
                    def step(name):
                        nonlocal interrupted
                        events.append(name)
                        if name == stage and not interrupted:
                            interrupted = True
                            raise m.RestartCommand()
                        return True
                    def clear():
                        self.assertFalse(job._composing)
                        events.append('clear')
                        return True
                    with patch.object(job, '_send_text', side_effect=lambda text: step('type_at' if text == '@' else 'type_command')), \
                         patch.object(job, '_press_enter', side_effect=lambda text: step('select' if text == '@' else 'send')), \
                         patch.object(job, '_sleep', return_value=False), \
                         patch.object(job, '_clear_interrupted_input', side_effect=clear):
                        self.assertTrue(job._command(command))
                    self.assertEqual(events[events.index('clear') + 1:], ['type_at', 'select', 'type_command', 'send'])
                    self.assertEqual(job._last_command, command)
                    self.assertEqual(job.done, 0)

    def test_focus_loss_detected_in_waits_and_before_input(self):
        for method in ('sleep', 'ready'):
            job = self.job()
            job._composing, job._command_submitted = True, False
            with patch.object(m, 'GetForegroundWindow', return_value=2):
                with self.assertRaises(m.RestartCommand):
                    if method == 'sleep':
                        job._sleep(0.5)
                    elif method == 'ready':
                        job._wait_until_ready()

    def test_resume_sends_three_backspaces_with_focus_checks(self):
        job = self.job()
        # Focus is lost again after the first Backspace. Send only the two
        # remaining Backspaces after returning, with no select-all input.
        foregrounds = [2, 1, 1, 2, 1, 1, 1, 1, 1, 1]
        with patch.object(m, 'IsWindow', return_value=True), \
             patch.object(m, 'GetForegroundWindow', side_effect=foregrounds), \
             patch.object(m, 'modifiers_held', return_value=False), \
             patch.object(m, 'find_child', return_value=10), \
             patch.object(m, 'focus_control', return_value=True), \
             patch.object(m, 'control_has_focus', return_value=True), \
             patch.object(m, 'release_stuck_keys'), patch.object(m, 'stuck_scans', set()), \
             patch.object(m, 'focused_text', return_value=''), \
             patch.object(m, 'press_keys', return_value=True) as keys, \
             patch.object(job, '_sleep', return_value=False):
            self.assertTrue(job._clear_interrupted_input())
        self.assertEqual([c.args for c in keys.call_args_list],
                         [(m.VK_BACK,), (m.VK_BACK,), (m.VK_BACK,)])

    def test_stop_during_pause_never_clears_or_restarts(self):
        job = self.job()
        job._stop_event.set()
        with patch.object(m, 'press_keys') as keys:
            self.assertFalse(job._clear_interrupted_input())
            self.assertFalse(job._command('수동'))
        keys.assert_not_called()

    def test_startup_focuses_input_without_deleting_or_waiting_for_draft(self):
        job = self.job()
        with patch.object(m, 'GetForegroundWindow', return_value=1), \
             patch.object(m, 'modifiers_held', return_value=False), \
             patch.object(m, 'is_responsive', return_value=True), \
             patch.object(m, 'find_child', return_value=10), \
             patch.object(m, 'focus_control', return_value=True) as focus, \
             patch.object(m, 'release_stuck_keys'), patch.object(m, 'stuck_scans', set()), \
             patch.object(m, 'focused_text', return_value='남은 글') as read, \
             patch.object(m, 'press_keys') as keys, \
             patch.object(job, '_clear_interrupted_input') as prepare, patch.object(job, '_sleep') as sleep:
            self.assertTrue(job._wait_until_ready())
        focus.assert_called_once_with(10)
        prepare.assert_not_called()
        read.assert_not_called()
        keys.assert_not_called()
        sleep.assert_not_called()
        self.assertIsNone(job.waiting)

    def test_sent_command_is_not_restarted_on_focus_loss(self):
        job = self.job()
        job._composing, job._command_submitted = True, True
        with patch.object(m, 'GetForegroundWindow', return_value=2):
            job._check_command_focus()  # no restart after final Enter


if __name__ == '__main__':
    unittest.main()
