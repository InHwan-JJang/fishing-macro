"""Shared diagnostic logging for the packaged app and its worker threads."""
import functools
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import sys
import threading
from datetime import datetime, timezone, timedelta

LOG = logging.getLogger('FishingMacro')
LOG.addHandler(logging.NullHandler())


class KSTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, timezone(timedelta(hours=9))).isoformat(timespec='milliseconds')


def setup_logging(base_directory, version):
    directory = Path(base_directory) / 'debug'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'fishing-macro.log'
    handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
    handler.setFormatter(KSTFormatter('%(asctime)s %(levelname)s pid=%(process)d [%(threadName)s] %(name)s %(message)s'))
    for old in list(LOG.handlers):
        if isinstance(old, RotatingFileHandler):
            LOG.removeHandler(old)
            old.close()
    LOG.addHandler(handler)
    LOG.setLevel(logging.DEBUG)
    LOG.propagate = False
    sys.excepthook = log_uncaught_exception
    threading.excepthook = log_thread_exception
    LOG.info('APP START version=%s python=%s platform=%s frozen=%s executable=%s cwd=%s log=%s',
             version, sys.version, platform.platform(), getattr(sys, 'frozen', False), sys.executable, os.getcwd(), path)
    return path


def log_uncaught_exception(exc_type, value, tb):
    LOG.critical('Unhandled main-thread exception', exc_info=(exc_type, value, tb))


def log_thread_exception(args):
    LOG.critical('Unhandled thread exception thread=%s', getattr(args.thread, 'name', None),
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def traced(function):
    """Trace user-facing operations without serializing widgets or chat snapshots."""
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        LOG.debug('BEGIN %s', function.__qualname__)
        try:
            result = function(*args, **kwargs)
        except Exception:
            LOG.exception('FAILED %s', function.__qualname__)
            raise
        LOG.debug('END %s', function.__qualname__)
        return result
    return wrapper
