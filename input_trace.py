"""Bounded, observation-only keyboard trace for the mention selection interval.

Only records while the requested chat is foreground and a mention is active.
No input is generated, suppressed, or converted to text by this observer.
"""
import ctypes
from ctypes import wintypes as wt
from collections import deque
import threading
import time

from debug_logging import LOG

INPUT_TAG = 0x464D4143  # FMAC: distinguish this process's SendInput events.


class KeyEvent(ctypes.Structure):
    _fields_ = [('vk', wt.DWORD), ('scan', wt.DWORD), ('flags', wt.DWORD),
                ('tick', wt.DWORD), ('extra', ctypes.c_size_t)]


class MentionTrace:
    def __init__(self):
        self.active = None
        self.events = deque(maxlen=512)
        self.serial = 0
        self.ready = threading.Event()
        self.stop_requested = threading.Event()
        self.installed = False
        self.thread = threading.Thread(target=self._run, name='MentionTrace', daemon=True)

    def start(self):
        self.thread.start()
        self.ready.wait(1.0)

    def begin(self, room):
        self.serial += 1
        self.active = (self.serial, room, time.monotonic() + 10)
        LOG.info('MENTION TRACE begin id=%s room=%s installed=%s', self.serial, room, self.installed)

    def record(self, event, foreground, message):
        active = self.active
        if not active or foreground != active[1] or time.monotonic() > active[2]:
            return
        origin = 'macro' if event.extra == INPUT_TAG else ('other-injected' if event.flags & 0x10 else 'unmarked')
        self.events.append((active[0], time.perf_counter(), message, event.vk, event.scan,
                            event.flags, event.tick, origin))

    def end(self):
        active, self.active = self.active, None
        # File I/O happens outside the low-level callback.
        while self.events:
            LOG.info('MENTION KEY id=%s time=%.6f msg=%s vk=%s scan=%s flags=%s tick=%s origin=%s',
                     *self.events.popleft())
        LOG.info('MENTION TRACE end id=%s', active[0] if active else None)

    def stop(self):
        self.active = None
        self.stop_requested.set()
        self.thread.join(1.0)

    def _run(self):
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
        def api(dll, name, result, *args):
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = result, args
            return fn
        install = api(user, 'SetWindowsHookExW', wt.HANDLE, ctypes.c_int, callback_type, wt.HINSTANCE, wt.DWORD)
        uninstall = api(user, 'UnhookWindowsHookEx', wt.BOOL, wt.HANDLE)
        forward = api(user, 'CallNextHookEx', ctypes.c_ssize_t, wt.HANDLE, ctypes.c_int, wt.WPARAM, wt.LPARAM)
        foreground = api(user, 'GetForegroundWindow', wt.HWND)
        module = api(kernel, 'GetModuleHandleW', wt.HMODULE, wt.LPCWSTR)
        peek = api(user, 'PeekMessageW', wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
        translate = api(user, 'TranslateMessage', wt.BOOL, ctypes.POINTER(wt.MSG))
        dispatch = api(user, 'DispatchMessageW', ctypes.c_ssize_t, ctypes.POINTER(wt.MSG))

        @callback_type
        def callback(code, message, pointer):
            try:
                if code >= 0 and self.active:
                    self.record(ctypes.cast(pointer, ctypes.POINTER(KeyEvent)).contents, foreground(), message)
            finally:
                return forward(None, code, message, pointer)

        hook = install(13, callback, module(None), 0)  # WH_KEYBOARD_LL
        self.installed = bool(hook)
        LOG.info('MENTION TRACE hook installed=%s error=%s', self.installed, ctypes.get_last_error() if not hook else 0)
        self.ready.set()
        if not hook:
            return
        try:
            message = wt.MSG()
            while not self.stop_requested.is_set():
                while peek(ctypes.byref(message), None, 0, 0, 1):
                    translate(ctypes.byref(message))
                    dispatch(ctypes.byref(message))
                self.stop_requested.wait(0.005)
        finally:
            uninstall(hook)
            self.installed = False
