import unittest
from unittest.mock import patch

import fishing_macro as m
import test_auto_release


def line(who, body):
    return f'[{who}] [오후 2:00] {body}'


class CoreCycleTests(unittest.TestCase):
    def test_silent_manual_does_not_steal_next_auto(self):
        text = '\n'.join([line('나', '@봇 낚시'), line('봇', '@사용자 자동어 출현'),
                          line('나', '@봇 수동'), line('나', '@봇 낚시'),
                          line('봇', '@사용자 자동어 출현')])
        self.assertEqual(m.my_replies(text, '나')[-1], ('낚시', ('auto',)))

    def test_separate_auto_card_and_other_player(self):
        for who, expected in [('나', ('auto',)), ('친구', None)]:
            text = '\n'.join([line('나', '@봇 낚시')] if who == '나' else [])
            if who != '나':
                text += line(who, '@봇 낚시')
            text += '\n' + line('봇', '@사용자 입질!') + '\n' + line('봇', '자동어 출현! 수동으로 쫓아내세요')
            self.assertEqual(m.latest_reply_after_my_command(text, '나'), expected)

    def test_old_auto_is_not_a_new_command(self):
        old = line('나', '@봇 낚시') + '\n' + line('봇', '@사용자 자동어 출현')
        self.assertFalse(m.has_new_command(old, old, '나'))
        self.assertTrue(m.has_new_command(old, old + '\n' + line('나', '@봇 수동'), '나'))
        self.assertFalse(m.has_new_command(old, old + '\n' + line('친구', '@봇 낚시'), '나'))
        self.assertFalse(m.has_new_command(old, line('나', '@봇 수동'), '나'))

    def test_unknown_reply_advances_to_next_cycle_without_counting_success(self):
        job, commands = test_auto_release.AutoReleaseTests().run_job([(), ('success', 2, 4000, None)])
        self.assertEqual(commands, ['낚시', '낚시'])
        self.assertEqual((job.done, job.end_reason), (1, 'finished'))

    def test_delayed_auto_retries_reads_not_fishing(self):
        job, commands = test_auto_release.AutoReleaseTests().run_job([(), ('auto',), (), ('success', 1, 4000, None)])
        self.assertEqual(commands, ['낚시', '낚시', '수동', '낚시'])
        self.assertEqual(job.done, 1)

    def test_failed_initial_read_sends_nothing(self):
        with patch('threading.Thread.start'):
            job = m.MacroJob(1, '나', 1, False)
        with patch.object(job, '_sleep', return_value=False), patch.object(job, '_wait_until_ready', return_value=True), \
             patch.object(m, 'copy_chat', return_value=None), patch.object(job, '_command') as send:
            job._run()
        send.assert_not_called()
        self.assertEqual(job.end_reason, 'read_failed')

    def test_second_check_finds_auto_at_two_and_half_seconds(self):
        with patch('threading.Thread.start'):
            job = m.MacroJob(1, '나', 1, False)
        job._last_enter = 0
        job.observer.baseline('')
        clock, reads = [0.0], []
        def sleep(seconds, watch=False):
            clock[0] += seconds
            return False
        def copy(room, deadline=None):
            reads.append(clock[0])
            return None if len(reads) == 1 else line('나', '@봇 낚시') + '\n' + line('봇', '@사용자 자동어 출현')
        with patch.object(job, '_sleep', side_effect=sleep), \
             patch.object(m.time, 'perf_counter', side_effect=lambda: clock[0]), \
             patch.object(m, 'GetForegroundWindow', return_value=1), patch.object(m, 'copy_chat', side_effect=copy):
            self.assertEqual(job._await_reply(), ('auto',))
        self.assertEqual(reads, [0.5, 2.5])
        self.assertEqual(clock[0], 3.0)

    def test_count_can_advance_after_unconfirmed_cycle(self):
        with patch('threading.Thread.start'):
            job = m.MacroJob(1, '나', 1, False)
        job.today = 10
        job._unconfirmed_catch = True
        self.assertFalse(job._stale(('success', 12, 4000, None)))
        self.assertTrue(job._stale(('success', 10, 4000, None)))

    def test_chord_is_one_input_batch(self):
        events = []
        def send(count, inputs, size):
            events.extend((inputs[i].ki.wScan, inputs[i].ki.dwFlags) for i in range(count))
            return count
        with patch.object(m, 'MapVirtualKeyW', side_effect=lambda vk, _: vk), patch.object(m, 'SendInput', side_effect=send) as sent:
            self.assertTrue(m.press_keys(m.VK_CONTROL, m.VK_C))
        self.assertEqual(sent.call_count, 1)
        self.assertEqual([e[0] for e in events], [m.VK_CONTROL, m.VK_C, m.VK_C, m.VK_CONTROL])
        self.assertEqual([bool(e[1] & m.KEYEVENTF_KEYUP) for e in events], [False, False, True, True])

    def test_failed_select_never_copies_or_focuses_edit(self):
        with patch.object(m, 'find_child', side_effect=[10, 20]), patch.object(m, 'GetForegroundWindow', return_value=1), \
             patch.object(m, 'modifiers_held', return_value=False), patch.object(m, 'get_clipboard_text', return_value='saved'), \
             patch.object(m, 'GetClipboardSequenceNumber', return_value=1), patch.object(m, 'focus_control', return_value=True) as focus, \
             patch.object(m, 'press_keys', return_value=False) as press, patch.object(m.time, 'sleep'):
            self.assertIsNone(m.copy_chat(1))
        self.assertEqual([c.args for c in press.call_args_list], [(m.VK_CONTROL, m.VK_A)])
        self.assertEqual([c.args for c in focus.call_args_list], [(10,)])

    def test_copy_timeout_keeps_list_focused(self):
        with patch.object(m, 'find_child', side_effect=[10, 20]), patch.object(m, 'GetForegroundWindow', return_value=1), \
             patch.object(m, 'modifiers_held', return_value=False), patch.object(m, 'get_clipboard_text', return_value='saved'), \
             patch.object(m, 'GetClipboardSequenceNumber', return_value=1), patch.object(m, 'focus_control', return_value=True) as focus, \
             patch.object(m, 'control_has_focus', return_value=True), patch.object(m, 'press_keys', return_value=True), \
             patch.object(m, 'wait_for_copied_text', return_value=None), patch.object(m.time, 'sleep'):
            self.assertIsNone(m.copy_chat(1))
        self.assertTrue(all(c.args == (10,) for c in focus.call_args_list))


if __name__ == '__main__':
    unittest.main()
