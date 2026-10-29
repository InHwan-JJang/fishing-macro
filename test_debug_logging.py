import logging
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

import debug_logging as diagnostics


class DebugLoggingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.old_hooks = sys.excepthook, threading.excepthook
        self.old_level = diagnostics.LOG.level
        self.old_propagate = diagnostics.LOG.propagate
        self.path = diagnostics.setup_logging(self.directory.name, 'test')

    def tearDown(self):
        for handler in list(diagnostics.LOG.handlers):
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                diagnostics.LOG.removeHandler(handler)
                handler.close()
        sys.excepthook, threading.excepthook = self.old_hooks
        diagnostics.LOG.setLevel(self.old_level)
        diagnostics.LOG.propagate = self.old_propagate
        self.directory.cleanup()

    def test_utf8_context_and_tracebacks_are_flushed(self):
        diagnostics.LOG.info('자동어 해제 시도=3')
        try:
            raise ValueError('테스트 예외')
        except ValueError:
            info = sys.exc_info()
            sys.excepthook(*info)
            threading.excepthook(SimpleNamespace(exc_type=info[0], exc_value=info[1], exc_traceback=info[2], thread=threading.current_thread()))
        content = self.path.read_text(encoding='utf-8')
        for expected in ('APP START', '+09:00', 'pid=', '자동어 해제 시도=3', 'Traceback', 'ValueError: 테스트 예외', 'Unhandled thread exception'):
            self.assertIn(expected, content)

    def test_rotation_retains_bounded_backups(self):
        handler = next(h for h in diagnostics.LOG.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
        handler.maxBytes = 300
        handler.backupCount = 2
        for index in range(15):
            diagnostics.LOG.info('event=%s %s', index, '내용' * 50)
        self.assertTrue(Path(str(self.path) + '.1').exists())
        self.assertTrue(Path(str(self.path) + '.2').exists())
        self.assertFalse(Path(str(self.path) + '.3').exists())
        self.assertIn('event=14', self.path.read_text(encoding='utf-8'))

    def test_traced_failure_preserves_exception(self):
        @diagnostics.traced
        def broken():
            raise RuntimeError('원인 보존')
        with self.assertRaisesRegex(RuntimeError, '원인 보존'):
            broken()
        self.assertIn('FAILED', self.path.read_text(encoding='utf-8'))

    def test_reconfiguration_does_not_duplicate_lines(self):
        diagnostics.setup_logging(self.directory.name, 'test-again')
        diagnostics.LOG.info('unique-marker')
        self.assertEqual(self.path.read_text(encoding='utf-8').count('unique-marker'), 1)
