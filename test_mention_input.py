import unittest
from unittest.mock import patch

import fishing_macro as m


class MentionInputTests(unittest.TestCase):
    def setUp(self):
        foreground = patch.object(m, 'GetForegroundWindow', return_value=1)
        foreground.start()
        self.addCleanup(foreground.stop)

    def job(self):
        with patch('threading.Thread.start'):
            return m.MacroJob(1, '나', 1, False)

    def test_at_enter_does_not_read_or_check_mention(self):
        job = self.job()
        with patch.object(job, '_wait_until_ready', return_value=True), \
             patch.object(m, 'focused_text') as box, \
             patch.object(m, 'press_keys', return_value=True) as keys:
            self.assertTrue(job._press_enter('@'))
        keys.assert_called_once_with(m.VK_RETURN)
        box.assert_not_called()

    def test_only_at_enter_command_enter_for_fishing_and_manual(self):
        for command in ('낚시', '수동'):
            job = self.job()
            events = []
            def send(text):
                events.append(text)
                return True
            def key(*keys):
                self.assertEqual(keys, (m.VK_RETURN,))
                events.append('Enter')
                return True
            with patch.object(job, '_send_text', side_effect=send), \
                 patch.object(job, '_sleep', return_value=False), \
                 patch.object(job, '_wait_until_ready', return_value=True), \
                 patch.object(m, 'focused_text') as box, \
                 patch.object(m, 'press_keys', side_effect=key), \
                 patch.object(m, 'copy_chat') as copy:
                self.assertTrue(job._command(command))
            self.assertEqual(events, ['@', 'Enter', command, 'Enter'])
            copy.assert_not_called()
            box.assert_not_called()

    def test_final_enter_does_not_read_input_or_wait_for_confirmation(self):
        job = self.job()
        with patch.object(job, '_wait_until_ready', return_value=True), \
             patch.object(m, 'focused_text') as box, patch.object(m, 'press_keys', return_value=True) as keys:
            self.assertTrue(job._press_enter('낚시'))
        keys.assert_called_once_with(m.VK_RETURN)
        box.assert_not_called()
        self.assertTrue(job._command_submitted)

    def test_no_key_cleanup_or_focus_change_between_at_and_enter(self):
        job = self.job()
        job._fresh_cycle = False
        with patch.object(m, 'GetForegroundWindow', return_value=1), \
             patch.object(m, 'modifiers_held', return_value=False), \
             patch.object(m, 'is_responsive', return_value=True), \
             patch.object(m, 'release_stuck_keys') as release, \
             patch.object(m, 'focus_control') as focus, patch.object(m, 'stuck_scans', set()):
            self.assertIsNone(job._blocker())
        release.assert_not_called()
        focus.assert_not_called()


if __name__ == '__main__':
    unittest.main()
