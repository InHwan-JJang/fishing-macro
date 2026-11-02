import unittest
from unittest.mock import patch

from input_trace import MentionTrace, KeyEvent, INPUT_TAG


class InputTraceTests(unittest.TestCase):
    def test_only_active_target_is_recorded(self):
        trace = MentionTrace()
        event = KeyEvent(vk=0x43, scan=46)
        trace.record(event, 1, 256)
        self.assertFalse(trace.events)
        trace.begin(1)
        trace.record(event, 2, 256)
        self.assertFalse(trace.events)
        trace.record(event, 1, 256)
        self.assertEqual(len(trace.events), 1)
        trace.end()
        trace.record(event, 1, 256)
        self.assertFalse(trace.events)

    def test_origin_tags_and_keyup_are_preserved(self):
        trace = MentionTrace()
        trace.begin(1)
        for extra, flags in ((INPUT_TAG, 0x90), (0, 0x10), (0, 0)):
            trace.record(KeyEvent(vk=0x11, scan=29, flags=flags, extra=extra), 1, 257)
        self.assertEqual([e[-1] for e in trace.events], ['macro', 'other-injected', 'unmarked'])
        self.assertEqual(trace.events[0][5], 0x90)

    def test_capture_expires_and_buffer_is_bounded(self):
        trace = MentionTrace()
        with patch('input_trace.time.monotonic', return_value=0):
            trace.begin(1)
            for _ in range(600):
                trace.record(KeyEvent(vk=13), 1, 256)
        self.assertEqual(len(trace.events), 512)
        with patch('input_trace.time.monotonic', return_value=11):
            trace.record(KeyEvent(vk=65), 1, 256)
        self.assertEqual(trace.events[-1][3], 13)


if __name__ == '__main__':
    unittest.main()
