"""낚시 매크로 - 카카오톡 낚시 봇 방에서 "@" → Enter → "낚시" → Enter 를 반복합니다.

* [시작] 또는 F9: 제목이 "낚시"로 시작하는 카톡 채팅방 창을 찾아 앞으로 가져온 뒤 바로 시작합니다.
* 한 번 반복: "@" → 500 ms → Enter → 500 ms → "낚시" → 500 ms → Enter → 봇 답장 확인 → 3초 대기
* 반복할 때마다 채팅 내용을 복사(Ctrl+A, Ctrl+C)해 봇 답장을 읽습니다.
    - "오늘 낚시: N / M" 으로 오늘 횟수를 세고, 한도(M)에 닿으면 멈춥니다. (한도 넘겨 치면 정지당함)
    - "자동어"를 낚았으면 "@" → Enter → "수동" → Enter 로 풀고 계속합니다.
    - 횟수 '자동': 오늘 한도를 알아서 다 채웁니다.  수동: 적은 횟수만큼 반복합니다.
* 그 채팅방 창이 앞에 있을 때만 입력합니다. 다른 창으로 바꾸면 일시정지, 다시 클릭하면 계속.
* F9 시작/정지, ESC 긴급 정지(채팅방이나 이 창이 앞에 있을 때)

빌드: build.bat
"""

import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import traceback
from collections import deque
from ctypes import wintypes as wt
from tkinter import messagebox, ttk

APP_TITLE = "낚시 매크로"
ICON_FILE = "fishing.ico"
ROOM_PREFIX = "낚시"            # 이 글자로 시작하는 카톡 채팅방을 찾음
TEXT_FISH, TEXT_MANUAL = "낚시", "수동"
GAP_S = 0.5                     # 키 사이 간격
WAIT_S = 3.0                    # 반복 대기
REPEAT_RANGE = (0, 9999)
DEFAULT_REPEAT = 4000
REPLY_FIRST_POLL_S = 0.7        # Enter 뒤 처음 채팅을 읽기까지 (봇 답장은 보통 1초 안에 옴)
REPLY_POLL_S = 0.5              # 답장이 아직 없으면 이 간격으로 다시 읽음 (읽기 1회 ≈ 0.2초)
MAX_AUTO_RELEASE = 3            # 자동어 해제를 연속으로 시도하는 최대 횟수
KEY_HOLD_S = 0.03
CHAR_GAP_S = 0.01
RESUME_DELAY_S = 0.5
RESPONSE_TIMEOUT_MS = 500
ENTER_READY_TIMEOUT_S = 1.0
SEND_CHECK_TIMEOUT_S = 1.5
ENTER_RETRIES = 2
MAX_READ_CHARS = 100000
POLL_MS = 50
UI_FONT = "Malgun Gothic"
SETTINGS_FILE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "FishingMacro", "settings.json")
CLIPBOARD_PRIVATE_FORMATS = ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                             "CanUploadToCloudClipboard")
WAIT_MESSAGES = {
    "window": "채팅방을 다시 클릭하면 계속합니다",
    "keys": "Shift·Ctrl·Alt를 떼면 계속합니다",
    "draft": "입력창의 글을 보내거나 지우면 계속합니다",
    "busy": "카톡이 응답하지 않아 기다리는 중",
    "unsent": "메시지가 안 보내짐 · 입력창을 정리하면 계속",
    "reply": "봇 답장을 기다리는 중",
    "auto": "자동어 해제 중",
    "stuck_auto": "자동어가 안 풀림 · 직접 확인해 주세요",
}

# ── Win32 ────────────────────────────────────────────────────────────────
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x0002, 0x0004, 0x0008
MAPVK_VK_TO_VSC = 0
VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU, VK_ESCAPE = 0x0D, 0x10, 0x11, 0x12, 0x1B
VK_LWIN, VK_RWIN, VK_A, VK_C, VK_F9 = 0x5B, 0x5C, 0x41, 0x43, 0x78
MODIFIER_VKS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY, TOKEN_ELEVATION = 0x0008, 20
WM_NULL, WM_GETTEXT, WM_GETTEXTLENGTH, WM_QUIT, WM_HOTKEY = 0x0000, 0x000D, 0x000E, 0x0012, 0x0312
SMTO_ABORTIFHUNG = 0x0002
PM_NOREMOVE = 0
MOD_NOREPEAT = 0x4000
NI_COMPOSITIONSTR, CPS_COMPLETE = 0x0015, 0x0001
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
MB_ICONINFORMATION = 0x40
HOTKEY_TOGGLE = 1
ROOM_CLASS, LIST_CLASS, EDIT_CLASS = "EVA_Window_Dblclk", "EVA_VH_ListControl_Dblclk", "RICHEDIT50W"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32")


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND),
                ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND), ("hwndMoveSize", wt.HWND),
                ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT)]


def _api(dll, name, restype, *argtypes):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = restype, argtypes
    return fn


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
SendInput = _api(user32, "SendInput", wt.UINT, wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
MapVirtualKeyW = _api(user32, "MapVirtualKeyW", wt.UINT, wt.UINT, wt.UINT)
GetAsyncKeyState = _api(user32, "GetAsyncKeyState", ctypes.c_short, ctypes.c_int)
GetForegroundWindow = _api(user32, "GetForegroundWindow", wt.HWND)
SetForegroundWindow = _api(user32, "SetForegroundWindow", wt.BOOL, wt.HWND)
GetFocus = _api(user32, "GetFocus", wt.HWND)
SetFocus = _api(user32, "SetFocus", wt.HWND, wt.HWND)
AttachThreadInput = _api(user32, "AttachThreadInput", wt.BOOL, wt.DWORD, wt.DWORD, wt.BOOL)
IsWindow = _api(user32, "IsWindow", wt.BOOL, wt.HWND)
IsWindowVisible = _api(user32, "IsWindowVisible", wt.BOOL, wt.HWND)
IsIconic = _api(user32, "IsIconic", wt.BOOL, wt.HWND)
ShowWindow = _api(user32, "ShowWindow", wt.BOOL, wt.HWND, ctypes.c_int)
EnumWindows = _api(user32, "EnumWindows", wt.BOOL, WNDENUMPROC, wt.LPARAM)
EnumChildWindows = _api(user32, "EnumChildWindows", wt.BOOL, wt.HWND, WNDENUMPROC, wt.LPARAM)
GetWindowTextW = _api(user32, "GetWindowTextW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
GetClassNameW = _api(user32, "GetClassNameW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
GetWindowThreadProcessId = _api(user32, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
GetGUIThreadInfo = _api(user32, "GetGUIThreadInfo", wt.BOOL, wt.DWORD, ctypes.POINTER(GUITHREADINFO))
SendMessageTimeoutW = _api(user32, "SendMessageTimeoutW", wt.LPARAM, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
                           wt.UINT, wt.UINT, ctypes.POINTER(ctypes.c_size_t))
MessageBoxW = _api(user32, "MessageBoxW", ctypes.c_int, wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT)
RegisterHotKey = _api(user32, "RegisterHotKey", wt.BOOL, wt.HWND, ctypes.c_int, wt.UINT, wt.UINT)
UnregisterHotKey = _api(user32, "UnregisterHotKey", wt.BOOL, wt.HWND, ctypes.c_int)
GetMessageW = _api(user32, "GetMessageW", wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
PeekMessageW = _api(user32, "PeekMessageW", wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
PostThreadMessageW = _api(user32, "PostThreadMessageW", wt.BOOL, wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)
OpenClipboard = _api(user32, "OpenClipboard", wt.BOOL, wt.HWND)
EmptyClipboard = _api(user32, "EmptyClipboard", wt.BOOL)
GetClipboardData = _api(user32, "GetClipboardData", wt.HANDLE, wt.UINT)
SetClipboardData = _api(user32, "SetClipboardData", wt.HANDLE, wt.UINT, wt.HANDLE)
CloseClipboard = _api(user32, "CloseClipboard", wt.BOOL)
GetClipboardSequenceNumber = _api(user32, "GetClipboardSequenceNumber", wt.DWORD)
RegisterClipboardFormatW = _api(user32, "RegisterClipboardFormatW", wt.UINT, wt.LPCWSTR)
GetCurrentThreadId = _api(kernel32, "GetCurrentThreadId", wt.DWORD)
GetCurrentProcess = _api(kernel32, "GetCurrentProcess", wt.HANDLE)
OpenProcess = _api(kernel32, "OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
CloseHandle = _api(kernel32, "CloseHandle", wt.BOOL, wt.HANDLE)
CreateMutexW = _api(kernel32, "CreateMutexW", wt.HANDLE, ctypes.c_void_p, wt.BOOL, wt.LPCWSTR)
GlobalAlloc = _api(kernel32, "GlobalAlloc", wt.HGLOBAL, wt.UINT, ctypes.c_size_t)
GlobalLock = _api(kernel32, "GlobalLock", ctypes.c_void_p, wt.HGLOBAL)
GlobalUnlock = _api(kernel32, "GlobalUnlock", wt.BOOL, wt.HGLOBAL)
GlobalFree = _api(kernel32, "GlobalFree", wt.HGLOBAL, wt.HGLOBAL)
OpenProcessToken = _api(advapi32, "OpenProcessToken", wt.BOOL, wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE))
GetTokenInformation = _api(advapi32, "GetTokenInformation", wt.BOOL, wt.HANDLE, ctypes.c_int, ctypes.c_void_p,
                           wt.DWORD, ctypes.POINTER(wt.DWORD))
ImmGetContext = _api(imm32, "ImmGetContext", wt.HANDLE, wt.HWND)
ImmNotifyIME = _api(imm32, "ImmNotifyIME", wt.BOOL, wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD)
ImmReleaseContext = _api(imm32, "ImmReleaseContext", wt.BOOL, wt.HWND, wt.HANDLE)


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def enable_dpi_awareness():
    """시스템 DPI 인식. (모니터별 인식은 Tk 창을 다른 배율의 모니터로 옮길 때 창이 커지는 문제가 있음)"""
    try:
        set_context = _api(user32, "SetProcessDpiAwarenessContext", wt.BOOL, ctypes.c_void_p)
        if set_context(ctypes.c_void_p(-2)):
            return
    except AttributeError:
        pass
    try:
        user32.SetProcessDPIAware()
    except AttributeError:
        pass


# ── 창 정보 ──────────────────────────────────────────────────────────────
def window_pid(hwnd):
    pid = wt.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def find_windows(top_filter):
    found = []

    @WNDENUMPROC
    def collect(hwnd, _):
        if top_filter(hwnd):
            found.append(hwnd)
        return True

    EnumWindows(collect, 0)
    return found


def find_child(parent, cls):
    found = []

    @WNDENUMPROC
    def collect(hwnd, _):
        if window_class(hwnd) == cls and IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    EnumChildWindows(parent, collect, 0)
    return found[0] if found else None


def find_fishing_room():
    """제목이 '낚시'로 시작하는 카톡 채팅방 창. 없으면 None."""
    rooms = find_windows(lambda h: window_class(h) == ROOM_CLASS and IsWindowVisible(h)
                         and window_title(h).startswith(ROOM_PREFIX))
    return rooms[0] if rooms else None


def bring_to_front(hwnd):
    """창을 앞으로 가져옵니다 (최소화돼 있으면 복원). 성공하면 True."""
    if IsIconic(hwnd):
        ShowWindow(hwnd, SW_RESTORE)
    me, other = GetCurrentThreadId(), GetWindowThreadProcessId(hwnd, None)
    attached = other != me and AttachThreadInput(me, other, True)
    try:
        SetForegroundWindow(hwnd)
    finally:
        if attached:
            AttachThreadInput(me, other, False)
    for _ in range(20):
        if GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def focus_control(hwnd):
    """다른 프로그램의 컨트롤에 키보드 포커스를 줍니다 (그 창이 앞에 있을 때)."""
    me, other = GetCurrentThreadId(), GetWindowThreadProcessId(hwnd, None)
    attached = other != me and AttachThreadInput(me, other, True)
    try:
        SetFocus(hwnd)
        return GetFocus() == hwnd
    finally:
        if attached:
            AttachThreadInput(me, other, False)


def is_responsive(hwnd):
    return bool(SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG, RESPONSE_TIMEOUT_MS, None))


def focused_text(hwnd):
    """hwnd 창에서 키보드 포커스가 있는 입력칸의 글. 입력칸이 아니거나 읽을 수 없으면 None."""
    thread_id = GetWindowThreadProcessId(hwnd, None)
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if not thread_id or not GetGUIThreadInfo(thread_id, ctypes.byref(info)) or not info.hwndFocus:
        return None
    if "edit" not in window_class(info.hwndFocus).lower():
        return None
    length = ctypes.c_size_t()
    if (not SendMessageTimeoutW(info.hwndFocus, WM_GETTEXTLENGTH, 0, 0, SMTO_ABORTIFHUNG,
                                RESPONSE_TIMEOUT_MS, ctypes.byref(length)) or length.value > MAX_READ_CHARS):
        return None
    buf = ctypes.create_unicode_buffer(length.value + 1)
    if not SendMessageTimeoutW(info.hwndFocus, WM_GETTEXT, len(buf), ctypes.addressof(buf), SMTO_ABORTIFHUNG,
                               RESPONSE_TIMEOUT_MS, ctypes.byref(length)):
        return None
    return buf.value


def is_elevated(pid=None):
    process = GetCurrentProcess() if pid is None else OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    token = wt.HANDLE()
    try:
        if not OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        elevated, size = wt.DWORD(), wt.DWORD()
        if not GetTokenInformation(token, TOKEN_ELEVATION, ctypes.byref(elevated), ctypes.sizeof(elevated),
                                   ctypes.byref(size)):
            return None
        return bool(elevated.value)
    finally:
        if token:
            CloseHandle(token)
        if pid is not None:
            CloseHandle(process)


def commit_ime():
    hwnd = GetFocus()
    himc = ImmGetContext(hwnd) if hwnd else None
    if himc:
        ImmNotifyIME(himc, NI_COMPOSITIONSTR, CPS_COMPLETE, 0)
        ImmReleaseContext(hwnd, himc)


def already_running():
    ctypes.set_last_error(0)
    CreateMutexW(None, False, "Local\\FishingMacro.SingleInstance")
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return False
    found = find_windows(lambda h: IsWindowVisible(h) and window_class(h) == "TkTopLevel"
                         and window_title(h).startswith(APP_TITLE) and window_pid(h) != os.getpid())
    if found:
        bring_to_front(found[0])
    else:
        MessageBoxW(None, "낚시 매크로가 이미 실행 중입니다.", APP_TITLE, MB_ICONINFORMATION)
    return True


# ── 키보드 ───────────────────────────────────────────────────────────────
stuck_scans = set()


def _key(scan, flags):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki.wScan, inp.ki.dwFlags = scan, flags
    return SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1


def _release(scan):
    for _ in range(50):
        if _key(scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP):
            stuck_scans.discard(scan)
            return
        time.sleep(0.02)
    stuck_scans.add(scan)


def release_stuck_keys():
    for scan in list(stuck_scans):
        if _key(scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP):
            stuck_scans.discard(scan)


def press_keys(*vks):
    """키(조합)를 스캔 코드로 눌렀다 뗍니다."""
    scans = [MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) for vk in vks]
    pressed = []
    try:
        for scan in scans:
            if not _key(scan, KEYEVENTF_SCANCODE):
                return False
            pressed.append(scan)
        time.sleep(KEY_HOLD_S)
        return True
    finally:
        for scan in reversed(pressed):
            _release(scan)


def type_unicode(text):
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i + 2], "little")
        if not _key(unit, KEYEVENTF_UNICODE):
            return False
        _key(unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
    return True


def modifiers_held():
    return any(GetAsyncKeyState(vk) & 0x8000 for vk in MODIFIER_VKS)


# ── 클립보드 ─────────────────────────────────────────────────────────────
def _open_clipboard():
    for _ in range(50):
        if OpenClipboard(None):
            return True
        time.sleep(0.01)
    return False


def get_clipboard_text():
    """클립보드의 글. 글이 아니면 None."""
    if not _open_clipboard():
        return None
    try:
        handle = GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            GlobalUnlock(handle)
    finally:
        CloseClipboard()


def set_clipboard(text):
    """클립보드에 text를 넣습니다. 클립보드 기록(Win+V)에는 남지 않게 표시합니다."""
    if not _open_clipboard():
        return False
    try:
        EmptyClipboard()
        items = [(CF_UNICODETEXT, text.encode("utf-16-le") + b"\0\0")]
        items += [(RegisterClipboardFormatW(name), b"\0\0\0\0") for name in CLIPBOARD_PRIVATE_FORMATS]
        for fmt, data in items:
            handle = GlobalAlloc(GMEM_MOVEABLE, len(data))
            ptr = GlobalLock(handle) if handle else None
            if ptr:
                ctypes.memmove(ptr, data, len(data))
                GlobalUnlock(handle)
                if SetClipboardData(fmt, handle):
                    continue
            if handle:
                GlobalFree(handle)
            if fmt == CF_UNICODETEXT:
                return False
        return True
    finally:
        CloseClipboard()


def copy_chat(room):
    """채팅방의 대화 내용을 전체 선택·복사해 글로 돌려줍니다. 사용자의 클립보드(글)는 되돌립니다. 실패하면 None."""
    chat_list, edit = find_child(room, LIST_CLASS), find_child(room, EDIT_CLASS)
    if not chat_list or GetForegroundWindow() != room:
        return None
    saved = get_clipboard_text()
    before = GetClipboardSequenceNumber()
    text = None
    try:
        if focus_control(chat_list):
            press_keys(VK_CONTROL, VK_A)
            time.sleep(0.1)
            press_keys(VK_CONTROL, VK_C)
            for _ in range(20):
                if GetClipboardSequenceNumber() != before:
                    text = get_clipboard_text()
                    break
                time.sleep(0.05)
    finally:
        if edit:
            focus_control(edit)
        if saved is not None and text is not None:
            set_clipboard(saved)
    return text


# ── 채팅 해석 ────────────────────────────────────────────────────────────
HEADER_RE = re.compile(r"^\[(.+?)\] \[(?:오전|오후) \d{1,2}:\d{2}\] (.*)$")
COMMAND_RE = re.compile(r"^@(\S+)\s+(낚시|수동)\s*$")
TODAY_RE = re.compile(r"오늘 낚시:\s*([\d,]+)\s*/\s*([\d,]+)")
ACHIEVE_RE = re.compile(r"([\d,]+)회 달성 보상")      # "🎁 3,000회 달성 보상" (50회마다도 나옴)
EXTRA_MARK = "추가 낚시"                              # 한도를 채운 뒤의 '추가 낚시' 답장 → 하지 않음
DEFAULT_LIMIT = 4000                                  # 한도를 아직 못 읽었을 때 표시용 (판정에는 봇이 알려 준 한도만 씀)


def _num(s):
    return int(s.replace(",", ""))


def parse_messages(text):
    """복사한 대화를 (보낸 사람, 본문) 목록으로. 여러 줄 메시지는 한 본문으로 합칩니다."""
    messages = []
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            messages.append([m.group(1), m.group(2)])
        elif messages and line.strip():
            messages[-1][1] += "\n" + line
    return [(sender, body) for sender, body in messages]


def classify_reply(body):
    """봇 답장 본문 →
    ("success", 오늘 횟수|None, 한도|None, 달성 횟수|None) | ("extra",) | ("achieve", 달성 횟수) | ("auto",)
    | ("cooldown",) | ("other",)"""
    if "자동어" in body:
        return ("auto",)
    if EXTRA_MARK in body:
        return ("extra",)
    achieve = ACHIEVE_RE.search(body)
    achieved = _num(achieve.group(1)) if achieve else None
    if "낚시 성공" in body:
        m = TODAY_RE.search(body)
        if m:
            return ("success", _num(m.group(1)), _num(m.group(2)), achieved)
        return ("success", None, None, achieved)
    if achieved is not None:
        return ("achieve", achieved)
    if "숨을 고른" in body or "아직" in body:
        return ("cooldown",)
    return ("other",)


def limit_hit(reply, limit):
    """답장이 '오늘 한도를 다 채웠다'는 뜻인지. limit(봇이 알려 준 한도)을 모르면 '달성 보상'으로는 판정하지 않음
    (한도가 4,000인 사람도 3,000회 달성 보상을 받으므로)."""
    if not reply:
        return False
    if reply[0] == "extra":
        return True
    if reply[0] == "achieve":
        return limit is not None and reply[1] >= limit
    if reply[0] == "success":
        return (reply[1] is not None and reply[1] >= reply[2]) or \
            (limit is not None and reply[3] is not None and reply[3] >= limit)
    return False


def limit_hit_after_my_command(text, user, limit):
    """내 마지막 명령 뒤에 온 봇 메시지 중 한도 도달을 뜻하는 것이 있는지. (한도 직전에만 사용)"""
    hit = False
    for sender, body in parse_messages(text):
        if sender == user and COMMAND_RE.match(body):
            hit = False
        elif body.startswith("@사용자") and limit_hit(classify_reply(body), limit):
            hit = True
    return hit


def my_replies(text, user):
    """내 명령("@봇 낚시"/"@봇 수동")마다 짝지어진 봇 답장. 봇은 "@사용자 …"로 답하므로(이름이 복사되지 않음)
    명령 순서대로 답장을 짝짓습니다. 마지막 원소가 내 마지막 명령이고, 답장이 아직 없으면 None입니다."""
    pending, results = deque(), []
    for sender, body in parse_messages(text):
        cmd = COMMAND_RE.match(body)
        if cmd and sender != cmd.group(1):
            pending.append((sender, cmd.group(2)))
            if sender == user:
                results.append([cmd.group(2), None])
        elif body.startswith("@사용자") and pending:
            who, _ = pending.popleft()
            if who == user:
                results[-1][1] = classify_reply(body)
    return [tuple(r) for r in results]


def latest_reply_after_my_command(text, user):
    """내 마지막 명령 뒤에 온 봇 답장 중 가장 최근 것(짝짓기가 어긋났을 때의 보조 수단). 없으면 None."""
    latest = None
    for sender, body in parse_messages(text):
        if sender == user and COMMAND_RE.match(body):
            latest = None
        elif body.startswith("@사용자"):
            latest = classify_reply(body)
    return latest


def format_duration(seconds):
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    if minutes:
        return f"{minutes}분 {secs}초"
    return f"{secs}초"


# ── 백그라운드 작업 ──────────────────────────────────────────────────────
class GlobalHotkeys(threading.Thread):
    def __init__(self, keys, events):
        super().__init__(daemon=True)
        self._keys, self._events, self._thread_id = keys, events, 0
        self.failed = []
        self.ready = threading.Event()

    def run(self):
        msg = wt.MSG()
        PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        self._thread_id = GetCurrentThreadId()
        registered = []
        for hotkey_id, vk in self._keys.items():
            if RegisterHotKey(None, hotkey_id, MOD_NOREPEAT, vk):
                registered.append(hotkey_id)
            else:
                self.failed.append(hotkey_id)
        self.ready.set()
        try:
            while GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self._events.put(msg.wParam)
        finally:
            for hotkey_id in registered:
                UnregisterHotKey(None, hotkey_id)

    def stop(self):
        if self._thread_id:
            PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


class MacroJob:
    """낚시 채팅방에서 낚시 명령을 반복하고 봇 답장을 읽습니다."""

    def __init__(self, target, user, repeat, auto):
        self.target, self.user, self.repeat, self.auto = target, user, repeat, auto
        self.done = 0                # 이번 실행에서 끝낸 반복 수
        self.today = None            # 봇이 알려 준 오늘 낚시 횟수
        self.limit = None            # 오늘 한도
        self.failures = self.resent = self.auto_releases = 0
        self.waiting = None
        self.end_reason = None       # "finished" | "limit" | "target_closed"
        self.error = None
        self.cycle_s = 3 * GAP_S + WAIT_S + 0.3
        self._last_enter = 0.0
        self._limit_seen = False     # 한도 직전 반복에서 '달성 보상'·'추가 낚시' 메시지를 봄
        self._fresh_cycle = True
        self._clears_after_send = False
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def running(self):
        return self._thread.is_alive()

    @property
    def remaining(self):
        if self.auto:
            return max(0, self.limit - self.today) if self.limit is not None and self.today is not None else None
        return max(0, self.repeat - self.done)

    def stop(self, wait=0.0):
        self._stop_event.set()
        self._thread.join(wait)

    def _run(self):
        try:
            if self._sleep(RESUME_DELAY_S, watch=True):
                return
            started = time.perf_counter()
            cycles = 0
            while True:
                self._fresh_cycle = True
                if not self._command(TEXT_FISH):
                    return
                reply = self._await_reply()      # 답장을 읽으면서 마지막 Enter부터 WAIT_S초를 기다림
                if reply is None:
                    return
                kind = reply[0] if reply else "none"
                if kind == "success":
                    self.auto_releases = 0
                    if reply[1] is not None:
                        self.today, self.limit = reply[1], reply[2]
                elif kind == "auto":
                    if not self._release_auto():
                        return
                    continue                        # 자동어 낚시는 횟수에 안 들어감 → 다시
                cycles += 1
                self.cycle_s = (time.perf_counter() - started) / cycles
                if kind not in ("cooldown", "extra"):
                    self.done += 1
                if limit_hit(reply, self.limit) or self._limit_seen:
                    self.limit = self.limit or DEFAULT_LIMIT
                    self.today = self.limit
                    self.end_reason = "limit"
                    return
                if not self.auto and self.done >= self.repeat:
                    self.end_reason = "finished"
                    return
        except Exception:
            self.error = traceback.format_exc()
        finally:
            release_stuck_keys()

    def _command(self, text):
        """"@" → Enter → text → Enter. 정지했거나 창이 닫혔으면 False."""
        if not self._send_text("@") or self._sleep(GAP_S, watch=True) or not self._press_enter("@"):
            return False
        if self._sleep(GAP_S, watch=True) or not self._send_text(text) or self._sleep(GAP_S, watch=True):
            return False
        return self._press_enter(text)

    def _await_reply(self):
        """마지막 Enter부터 WAIT_S초 동안 기다리면서 내 명령에 대한 봇 답장을 읽습니다.
        (읽는 데 걸린 시간만큼 대기가 줄어 한 반복이 늘 같은 길이) 답장을 못 찾으면 (), 정지했으면 None."""
        deadline = self._last_enter + WAIT_S
        reply, fallback = None, None
        self.waiting = "reply"
        try:
            if self._sleep(REPLY_FIRST_POLL_S, watch=True):
                return None
            while not self._stop_event.is_set():
                if GetForegroundWindow() == self.target:
                    text = copy_chat(self.target)
                    if text:
                        replies = my_replies(text, self.user)
                        if self._near_limit() and limit_hit_after_my_command(text, self.user, self.limit):
                            self._limit_seen = True    # 3000번째는 답장이 둘(성공+달성)로 오기도 함
                        if replies and replies[-1][1] is not None and not self._stale(replies[-1][1]):
                            reply = replies[-1][1]
                            # 한도 직전인데 답장에 횟수가 없으면, 뒤따라올 '달성' 메시지를 대기 끝까지 더 읽음
                            if not (self._near_limit() and reply[0] == "success" and reply[1] is None
                                    and not self._limit_seen):
                                break
                        fallback = latest_reply_after_my_command(text, self.user)
                if time.perf_counter() >= deadline:
                    break
                if self._sleep(min(REPLY_POLL_S, max(0.0, deadline - time.perf_counter()))):
                    return None
        finally:
            self.waiting = None
        if reply is None:        # 짝짓기가 어긋났으면 내 명령 뒤에 온 마지막 답장을 씀
            reply = () if fallback is None or self._stale(fallback) else fallback
        if self._sleep(max(0.0, deadline - time.perf_counter()), watch=True):
            return None
        return reply

    def _near_limit(self):
        return self.today is not None and self.limit is not None and self.today >= self.limit - 1

    def _stale(self, reply):
        """'낚시 성공' 답장인데 오늘 횟수가 늘지 않았으면 남의 것이거나 이전 것."""
        return reply and reply[0] == "success" and reply[1] is not None and self.today is not None \
            and reply[1] <= self.today

    def _release_auto(self):
        """"@" → Enter → "수동" → Enter 로 자동어를 풉니다. 여러 번 해도 안 풀리면 사용자에게 맡기고 기다립니다."""
        self.auto_releases += 1
        if self.auto_releases > MAX_AUTO_RELEASE:
            self.waiting = "stuck_auto"
            while not self._stop_event.is_set():           # 사용자가 직접 풀고 창을 다시 클릭하면 계속
                if self._sleep(1.0):
                    return False
                if GetForegroundWindow() == self.target and self.waiting != "stuck_auto":
                    break
            self.auto_releases = 0
            return not self._stop_event.is_set()
        self.waiting = "auto"
        if self._sleep(GAP_S, watch=True) or not self._command(TEXT_MANUAL):
            return False
        return self._await_reply() is not None

    def _send_text(self, text):
        for i, piece in enumerate(text):
            if i and self._sleep(CHAR_GAP_S):
                return False
            if not self._wait_until_ready():
                return False
            self._fresh_cycle = False
            if not type_unicode(piece):
                self.failures += 1
        return True

    def _press_enter(self, typed):
        if typed:
            self._wait_box(lambda text: text.endswith(typed), ENTER_READY_TIMEOUT_S)
        for attempt in range(1 + ENTER_RETRIES):
            if not self._wait_until_ready():
                return False
            if attempt:
                self.resent += 1
            if not press_keys(VK_RETURN):
                self.failures += 1
            self._last_enter = time.perf_counter()
            self._fresh_cycle = False
            if not typed:
                return True
            sent = self._wait_box(self._sent_check(typed), SEND_CHECK_TIMEOUT_S)
            if self._stop_event.is_set():
                return False
            if sent is not False:
                return True
        self.waiting = "unsent"
        while not self._stop_event.is_set():
            if GetForegroundWindow() == self.target:
                text = focused_text(self.target)
                if text is None or not text.endswith(typed):
                    self.waiting = None
                    return True
            self._sleep(0.2)
        return False

    def _sent_check(self, typed):
        def sent(text):
            if not text:
                self._clears_after_send = True
            return not text.endswith(typed)
        return sent

    def _wait_box(self, predicate, timeout):
        deadline = time.perf_counter() + timeout
        while True:
            if GetForegroundWindow() == self.target:
                text = focused_text(self.target)
                if text is None:
                    return None
                if predicate(text):
                    return True
            if time.perf_counter() >= deadline:
                return False
            if self._sleep(0.03):
                return None

    def _wait_until_ready(self):
        while not self._stop_event.is_set():
            reason = self._blocker()
            if reason is None:
                if self.waiting is None:
                    return True
                self.waiting = None
                self._sleep(RESUME_DELAY_S)
            elif reason == "closed":
                self.end_reason = "target_closed"
                return False
            else:
                self.waiting = reason
                self._sleep(0.1)
        return False

    def _blocker(self):
        if GetForegroundWindow() != self.target:
            return "window" if IsWindow(self.target) else "closed"
        release_stuck_keys()
        if modifiers_held():
            return "keys"
        if not is_responsive(self.target):
            return "busy"
        if self._fresh_cycle and self._clears_after_send and focused_text(self.target):
            return "draft"
        return None

    def _sleep(self, seconds, watch=False):
        deadline = time.perf_counter() + seconds
        while not self._stop_event.is_set():
            if watch and GetForegroundWindow() != self.target:
                self.waiting = "window"
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return False
            time.sleep(min(remaining, 0.05))
        return True


# ── 설정 저장 ────────────────────────────────────────────────────────────
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


# ── 화면 ─────────────────────────────────────────────────────────────────
class App:
    def __init__(self, root):
        self.root = root
        self.job = None
        self._dialog_open = False
        self._idle = ("대기 중", "")
        self._notice_text, self._notice_until = "", 0.0
        self._esc_was_down = False
        self._poll_id = None
        settings = load_settings()

        root.title(APP_TITLE)
        root.resizable(False, False)
        root.report_callback_exception = self._report_exception
        try:
            root.iconbitmap(default=resource_path(ICON_FILE))
        except tk.TclError:
            pass
        self._build_ui(settings)

        self.hotkey_events = queue.Queue()
        self.hotkeys = GlobalHotkeys({HOTKEY_TOGGLE: VK_F9}, self.hotkey_events)
        self.hotkeys.start()
        self.hotkeys.ready.wait(1.0)
        self._f9_ok = HOTKEY_TOGGLE not in self.hotkeys.failed
        key = " (F9)" if self._f9_ok else ""
        self.start_btn.configure(text=f"▶ 시작{key}")
        self.stop_btn.configure(text=f"■ 정지{key}")

        root.protocol("WM_DELETE_WINDOW", self.close)
        self._poll()
        if self.user_var.get().strip():          # 유저이름이 저장돼 있으면 켜자마자 시작
            root.after(600, self.start)

    def _build_ui(self, settings):
        style = ttk.Style(self.root)
        style.configure(".", font=(UI_FONT, 10))
        style.configure("Big.TButton", font=(UI_FONT, 11, "bold"), padding=(6, 5))
        style.configure("Status.TLabel", font=(UI_FONT, 10, "bold"))
        style.configure("Detail.TLabel", font=(UI_FONT, 9), foreground="#555555")
        number_ok = (self.root.register(lambda t: re.fullmatch(r"[0-9]{0,4}", t) is not None), "%P")

        frame = ttk.Frame(self.root, padding=(12, 10))
        frame.grid()
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="유저이름").grid(row=0, column=0, sticky="w", pady=2)
        self.user_var = tk.StringVar(value=str(settings.get("user", "")))
        self.user_entry = ttk.Entry(frame, textvariable=self.user_var, width=14, font=(UI_FONT, 10))
        self.user_entry.grid(row=0, column=1, columnspan=2, sticky="w", padx=(8, 0), pady=2)
        # 한글 조합 중인 글자는 IME의 작은 창에 그려지는데 '항상 위' 창 뒤에 가려지므로, 입력하는 동안만 끔
        self.user_entry.bind("<FocusIn>", lambda _e: self.root.attributes("-topmost", False))
        self.user_entry.bind("<FocusOut>", lambda _e: self._apply_topmost())

        ttk.Label(frame, text="횟수").grid(row=1, column=0, sticky="w", pady=2)
        self.repeat_var = tk.StringVar(value=str(settings.get("repeat", DEFAULT_REPEAT)))
        self.repeat_box = ttk.Spinbox(frame, textvariable=self.repeat_var, from_=REPEAT_RANGE[0], to=REPEAT_RANGE[1],
                                      increment=100, width=6, justify="right", font=(UI_FONT, 10),
                                      validate="key", validatecommand=number_ok)
        self.repeat_box.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=2)
        self.auto_var = tk.BooleanVar(value=bool(settings.get("auto", True)))
        self.auto_check = ttk.Checkbutton(frame, text="자동", variable=self.auto_var, command=self._apply_auto)
        self.auto_check.grid(row=1, column=2, sticky="w", padx=(8, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 6))
        buttons.columnconfigure((0, 1), weight=1, uniform="btn")
        self.start_btn = ttk.Button(buttons, style="Big.TButton", command=self.start)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.start_btn.bind("<ButtonPress-1>", lambda _e: commit_ime())
        self.stop_btn = ttk.Button(buttons, style="Big.TButton", command=self.stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        self.status_var, self.detail_var = tk.StringVar(), tk.StringVar()
        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel", width=30).grid(
            row=3, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, textvariable=self.detail_var, style="Detail.TLabel", width=36).grid(
            row=4, column=0, columnspan=3, sticky="w")

        self.topmost_var = tk.BooleanVar(value=bool(settings.get("topmost", True)))
        ttk.Checkbutton(frame, text="항상 위에 표시", variable=self.topmost_var, command=self._apply_topmost).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._apply_topmost()
        self._apply_auto()

    def _apply_auto(self):
        self.repeat_box.configure(state="disabled" if self.auto_var.get() or self.job else "normal")

    def _apply_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    def _settings(self):
        user = self.user_var.get().strip().lstrip("@")
        if not user:
            raise ValueError("유저이름(카톡 이름)을 입력하세요. 예: 정인환")
        try:
            repeat = int(self.repeat_var.get())
        except ValueError:
            repeat = -1
        if not REPEAT_RANGE[0] <= repeat <= REPEAT_RANGE[1]:
            raise ValueError(f"횟수는 {REPEAT_RANGE[0]} ~ {REPEAT_RANGE[1]:,} 사이로 입력하세요.")
        return dict(user=user, repeat=repeat, auto=self.auto_var.get())

    # ── 동작 ─────────────────────────────────────────────────────────────
    def start(self):
        if self.job:
            return
        try:
            settings = self._settings()
        except ValueError as error:
            self._warn(str(error))
            return
        save_settings(dict(settings, topmost=self.topmost_var.get()))
        room = find_fishing_room()
        if room is None:
            self._idle = ("채팅방 없음", f"'{ROOM_PREFIX}'로 시작하는 카톡 채팅방을 열어 주세요")
            return
        if is_elevated(window_pid(room)) and not is_elevated():
            self._warn("카카오톡이 관리자 권한으로 실행 중이라 입력이 전달되지 않습니다.\n"
                       "이 매크로도 관리자 권한으로 실행하세요.")
            return
        if not bring_to_front(room):
            self._idle = ("시작 실패", "채팅방 창을 앞으로 가져오지 못했습니다. 한 번 클릭해 주세요")
            return
        self.job = MacroJob(room, **settings)
        self._set_busy(True)

    def stop(self):
        job, self.job = self.job, None
        if job is None:
            return
        job.stop(wait=1.5)
        self._idle = (f"정지됨 · {self._progress(job)}", "")
        self._set_busy(False)

    def toggle(self):
        self.stop() if self.job else self.start()

    def close(self):
        try:
            save_settings(dict(self._settings(), topmost=self.topmost_var.get()))
        except ValueError:
            pass
        if self.job:
            self.job.stop(wait=1.5)
        release_stuck_keys()
        self.hotkeys.stop()
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
        self.root.destroy()

    def _finish_job(self):
        job, self.job = self.job, None
        self._set_busy(False)
        progress = self._progress(job)
        if job.end_reason == "finished":
            self._idle = (f"완료 · {progress}", "")
        elif job.end_reason == "limit":
            self._idle = (f"오늘 한도 도달 · {progress}", "")
        elif job.end_reason == "target_closed":
            self._idle = (f"채팅방이 닫혀 정지 · {progress}", "")
        elif job.error:
            self._idle = (f"오류로 정지 · {progress}", "")
            self._error_dialog("입력 도중 오류가 발생해 정지했습니다.\n\n" + job.error[-1500:])
        else:
            self._idle = (f"정지됨 · {progress}", "")

    @staticmethod
    def _progress(job):
        if job.today is not None and job.limit is not None:
            return f"오늘 {job.today:,} / {job.limit:,}"
        return f"{job.done:,} / {job.repeat:,}" if not job.auto else f"{job.done:,}번"

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.user_entry, self.auto_check, self.start_btn):
            widget.configure(state=state)
        self._apply_auto()
        self.stop_btn.configure(state="normal" if busy else "disabled")

    def _notice(self, text, seconds=2.5):
        self._notice_text, self._notice_until = text, time.monotonic() + seconds

    def _take_hotkeys(self):
        keys = []
        while True:
            try:
                keys.append(self.hotkey_events.get_nowait())
            except queue.Empty:
                return keys

    def _esc_applies(self):
        if not self.job:
            return False
        foreground = GetForegroundWindow()
        return foreground == self.job.target or bool(foreground and window_pid(foreground) == os.getpid())

    def _warn(self, message):
        self._modal(messagebox.showwarning, message)

    def _error_dialog(self, message):
        self._modal(messagebox.showerror, message)

    def _modal(self, show, message):
        self._dialog_open = True
        try:
            show(APP_TITLE, message, parent=self.root)
        finally:
            self._dialog_open = False
            self._take_hotkeys()

    def _report_exception(self, exc, value, tb):
        self._error_dialog("예기치 못한 오류가 발생했습니다.\n\n"
                           + "".join(traceback.format_exception(exc, value, tb))[-1500:])

    # ── 주기적 갱신 ──────────────────────────────────────────────────────
    def _poll(self):
        try:
            esc = GetAsyncKeyState(VK_ESCAPE)
            esc_down = bool(esc & 0x8000)
            esc_pressed = (esc_down and not self._esc_was_down) or bool(esc & 1)
            self._esc_was_down = esc_down
            hotkeys = self._take_hotkeys()
            if esc_pressed and self._esc_applies():
                self.stop()
                self._notice("ESC를 눌러 정지했습니다")
            elif HOTKEY_TOGGLE in hotkeys and not self._dialog_open:
                self.toggle()
            if self.job and not self.job.running:
                self._finish_job()
            if stuck_scans and not self.job:
                release_stuck_keys()
            self._render_status()
        finally:
            self._poll_id = self.root.after(POLL_MS, self._poll)

    def _render_status(self):
        now = time.monotonic()
        job = self.job
        if job:
            progress = self._progress(job)
            if job.waiting == "window":
                status, detail = f"일시정지 · {progress}", WAIT_MESSAGES["window"]
            elif job.waiting in ("reply", None):
                status = f"실행 중 · {progress}"
                left = job.remaining
                detail = f"남은 시간 약 {format_duration(left * job.cycle_s)}" if left is not None else "오늘 횟수 확인 중"
            else:
                status, detail = f"대기 중 · {progress}", WAIT_MESSAGES[job.waiting]
        else:
            status, detail = self._idle
        if stuck_scans:
            detail = "관리자 권한 창이 앞에 있어 키를 떼지 못함 · 다른 창을 클릭하세요"
        if now < self._notice_until:
            detail = self._notice_text
        for var, text in ((self.status_var, status), (self.detail_var, detail)):
            if var.get() != text:
                var.set(text)
        title = f"{APP_TITLE} - {self._progress(job)}" if job else APP_TITLE
        if self.root.title() != title:
            self.root.title(title)


def main():
    if already_running():
        return
    enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
