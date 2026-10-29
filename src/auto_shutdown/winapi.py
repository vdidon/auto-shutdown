"""ctypes bindings for the Windows APIs the application needs.

No external dependency: everything goes through `ctypes`, which avoids bundling
`pywin32` (a compiled binary) and works on any CPython version.

Prototypes (`argtypes` / `restype`) are always declared. Without them, ctypes
truncates handles to 32 bits on a 64-bit Python and calls fail silently and
non-reproducibly.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

# ---------------------------------------------------------------------------
# Types missing from ctypes.wintypes
# ---------------------------------------------------------------------------

LRESULT = ctypes.c_ssize_t
HCURSOR = ctypes.c_void_p
HBRUSH = ctypes.c_void_p

WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
powrprof = ctypes.WinDLL("powrprof", use_last_error=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WM_DESTROY: Final = 0x0002
WM_CLOSE: Final = 0x0010
WM_QUIT: Final = 0x0012
WM_NULL: Final = 0x0000
WM_COMMAND: Final = 0x0111
WM_POWERBROADCAST: Final = 0x0218
WM_APP: Final = 0x8000

#: Private message sent by the notification area to our window.
WM_TRAYICON: Final = WM_APP + 1
#: Private message letting another thread ask the UI thread to perform an action.
WM_INVOKE: Final = WM_APP + 2

WM_LBUTTONUP: Final = 0x0202
WM_LBUTTONDBLCLK: Final = 0x0203
WM_RBUTTONUP: Final = 0x0205

# PBT_* events received in WM_POWERBROADCAST.
PBT_APMSUSPEND: Final = 0x0004
PBT_APMRESUMESUSPEND: Final = 0x0007
PBT_APMRESUMEAUTOMATIC: Final = 0x0012

DEVICE_NOTIFY_WINDOW_HANDLE: Final = 0x00000000

# Notification area.
NIM_ADD: Final = 0x00000000
NIM_MODIFY: Final = 0x00000001
NIM_DELETE: Final = 0x00000002
NIF_MESSAGE: Final = 0x00000001
NIF_ICON: Final = 0x00000002
NIF_TIP: Final = 0x00000004
NIF_INFO: Final = 0x00000010
NIIF_INFO: Final = 0x00000001
NIIF_WARNING: Final = 0x00000002

# Menus.
MF_STRING: Final = 0x00000000
MF_SEPARATOR: Final = 0x00000800
MF_GRAYED: Final = 0x00000001
MF_CHECKED: Final = 0x00000008
MF_POPUP: Final = 0x00000010
TPM_RIGHTBUTTON: Final = 0x0002
TPM_RETURNCMD: Final = 0x0100

# Windows.
CW_USEDEFAULT: Final = -0x80000000
WS_OVERLAPPED: Final = 0x00000000

# Privileges.
TOKEN_ADJUST_PRIVILEGES: Final = 0x0020
TOKEN_QUERY: Final = 0x0008
SE_PRIVILEGE_ENABLED: Final = 0x00000002
SE_SHUTDOWN_NAME: Final = "SeShutdownPrivilege"

# ExitWindowsEx.
EWX_LOGOFF: Final = 0x00000000
EWX_SHUTDOWN: Final = 0x00000001
EWX_REBOOT: Final = 0x00000002
EWX_FORCEIFHUNG: Final = 0x00000010
SHTDN_REASON_MAJOR_OTHER: Final = 0x00000000
SHTDN_REASON_MINOR_OTHER: Final = 0x00000000
SHTDN_REASON_FLAG_PLANNED: Final = 0x80000000

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------


class POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class MSG(ctypes.Structure):
    _fields_ = (
        ("hWnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    )


class WNDCLASSW(ctypes.Structure):
    _fields_ = (
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    )


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    )


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = (("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD))


class LUID(ctypes.Structure):
    _fields_ = (("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG))


class LUID_AND_ATTRIBUTES(ctypes.Structure):  # noqa: N801  (Windows API name)
    _fields_ = (("Luid", LUID), ("Attributes", wintypes.DWORD))


class TOKEN_PRIVILEGES(ctypes.Structure):  # noqa: N801  (Windows API name)
    _fields_ = (("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1))


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


# ---------------------------------------------------------------------------
# Prototypes
# ---------------------------------------------------------------------------

user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
user32.RegisterClassW.restype = wintypes.ATOM

user32.CreateWindowExW.argtypes = (
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
)
user32.CreateWindowExW.restype = wintypes.HWND

user32.DefWindowProcW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
user32.DefWindowProcW.restype = LRESULT

user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.DestroyWindow.restype = wintypes.BOOL

user32.GetMessageW.argtypes = (
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
user32.GetMessageW.restype = ctypes.c_int

user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
user32.DispatchMessageW.restype = LRESULT

user32.PostMessageW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
user32.PostMessageW.restype = wintypes.BOOL

user32.PostQuitMessage.argtypes = (ctypes.c_int,)
user32.PostQuitMessage.restype = None

user32.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
user32.RegisterWindowMessageW.restype = wintypes.UINT

user32.RegisterSuspendResumeNotification.argtypes = (wintypes.HANDLE, wintypes.DWORD)
user32.RegisterSuspendResumeNotification.restype = wintypes.HANDLE

user32.UnregisterSuspendResumeNotification.argtypes = (wintypes.HANDLE,)
user32.UnregisterSuspendResumeNotification.restype = wintypes.BOOL

user32.CreatePopupMenu.argtypes = ()
user32.CreatePopupMenu.restype = wintypes.HMENU

user32.AppendMenuW.argtypes = (
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_size_t,
    wintypes.LPCWSTR,
)
user32.AppendMenuW.restype = wintypes.BOOL

user32.TrackPopupMenu.argtypes = (
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.LPVOID,
)
user32.TrackPopupMenu.restype = wintypes.BOOL

user32.DestroyMenu.argtypes = (wintypes.HMENU,)
user32.DestroyMenu.restype = wintypes.BOOL

user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.GetCursorPos.restype = wintypes.BOOL

user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.restype = wintypes.BOOL

user32.GetLastInputInfo.argtypes = (ctypes.POINTER(LASTINPUTINFO),)
user32.GetLastInputInfo.restype = wintypes.BOOL

user32.LockWorkStation.argtypes = ()
user32.LockWorkStation.restype = wintypes.BOOL

user32.ExitWindowsEx.argtypes = (wintypes.UINT, wintypes.DWORD)
user32.ExitWindowsEx.restype = wintypes.BOOL

user32.CreateIconFromResourceEx.argtypes = (
    ctypes.POINTER(ctypes.c_byte),
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)
user32.CreateIconFromResourceEx.restype = wintypes.HICON

user32.DestroyIcon.argtypes = (wintypes.HICON,)
user32.DestroyIcon.restype = wintypes.BOOL

kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

kernel32.GetTickCount64.argtypes = ()
kernel32.GetTickCount64.restype = ctypes.c_ulonglong

kernel32.GetCurrentProcess.argtypes = ()
kernel32.GetCurrentProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE

kernel32.GetUserPreferredUILanguages.argtypes = (
    wintypes.DWORD,
    ctypes.POINTER(wintypes.ULONG),
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.ULONG),
)
kernel32.GetUserPreferredUILanguages.restype = wintypes.BOOL

shell32.Shell_NotifyIconW.argtypes = (wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
shell32.Shell_NotifyIconW.restype = wintypes.BOOL

advapi32.OpenProcessToken.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
)
advapi32.OpenProcessToken.restype = wintypes.BOOL

advapi32.LookupPrivilegeValueW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.POINTER(LUID),
)
advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL

advapi32.AdjustTokenPrivileges.argtypes = (
    wintypes.HANDLE,
    wintypes.BOOL,
    ctypes.POINTER(TOKEN_PRIVILEGES),
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.LPVOID,
)
advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL

powrprof.SetSuspendState.argtypes = (wintypes.BOOL, wintypes.BOOL, wintypes.BOOL)
powrprof.SetSuspendState.restype = wintypes.BOOL

# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

ERROR_ALREADY_EXISTS: Final = 183
MUI_LANGUAGE_NAME: Final = 0x8


def preferred_ui_languages() -> list[str]:
    """User's display languages, most preferred first (e.g. `["fr-FR", "en-US"]`).

    Returns an empty list if Windows cannot provide them.
    """
    count = wintypes.ULONG()
    size = wintypes.ULONG()
    if not kernel32.GetUserPreferredUILanguages(
        MUI_LANGUAGE_NAME, ctypes.byref(count), None, ctypes.byref(size)
    ):
        return []
    buffer = ctypes.create_unicode_buffer(size.value)
    if not kernel32.GetUserPreferredUILanguages(
        MUI_LANGUAGE_NAME, ctypes.byref(count), buffer, ctypes.byref(size)
    ):
        return []
    # Double-null-terminated list: names separated by NUL, ending with an empty one.
    names = ctypes.wstring_at(ctypes.addressof(buffer), size.value)
    return [name for name in names.split("\0") if name]


def idle_seconds() -> float:
    """Time elapsed since the last keyboard/mouse input, in seconds.

    Relies on `GetLastInputInfo`, whose counter uses the same time base as
    `GetTickCount`: both are read together to avoid any 32-bit wrap-around
    problem.
    """
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    now32 = kernel32.GetTickCount64() & 0xFFFFFFFF
    delta = (now32 - info.dwTime) & 0xFFFFFFFF
    return delta / 1000.0


def enable_shutdown_privilege() -> bool:
    """Enable `SeShutdownPrivilege` for the current process.

    Required by `ExitWindowsEx` (shutdown, restart, log off).
    Sleep and hibernate do not need it.
    """
    token = wintypes.HANDLE()
    process = kernel32.GetCurrentProcess()
    if not advapi32.OpenProcessToken(
        process, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)
    ):
        return False
    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, SE_SHUTDOWN_NAME, ctypes.byref(luid)):
            return False
        privileges = TOKEN_PRIVILEGES()
        privileges.PrivilegeCount = 1
        privileges.Privileges[0].Luid = luid
        privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None)
        # AdjustTokenPrivileges returns TRUE even on partial success:
        # only GetLastError tells the two cases apart.
        return ctypes.get_last_error() == 0
    finally:
        kernel32.CloseHandle(token)


def acquire_single_instance_mutex(name: str) -> int | None:
    """Create a named mutex; return `None` if an instance is already running.

    The returned handle must stay alive for the whole lifetime of the process.
    """
    handle = kernel32.CreateMutexW(None, True, name)
    if not handle:
        return None
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def make_icon(rgb: tuple[int, int, int], size: int = 32) -> wintypes.HICON:
    """Build a round icon of the requested color in memory.

    Avoids bundling `.ico` files and lets the icon reflect the application
    state through its color. The icon is built in the format of an `RT_ICON`
    resource — a `BITMAPINFOHEADER` of double height (color plane then AND
    mask) followed by BGRA pixels stored bottom-up — then converted by
    `CreateIconFromResourceEx`.
    """
    red, green, blue = rgb
    header = BITMAPINFOHEADER(
        biSize=ctypes.sizeof(BITMAPINFOHEADER),
        biWidth=size,
        biHeight=size * 2,
        biPlanes=1,
        biBitCount=32,
        biCompression=0,
        biSizeImage=size * size * 4,
    )

    pixels = bytearray(size * size * 4)
    centre = (size - 1) / 2.0
    radius = size / 2.0 - 1.5
    for row in range(size):
        # Rows are stored bottom-up.
        y = size - 1 - row
        for x in range(size):
            distance = ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
            # One-pixel gradient at the edge: enough to smooth the circle.
            alpha = max(0.0, min(1.0, radius - distance + 0.5))
            offset = (row * size + x) * 4
            pixels[offset] = int(blue * alpha)
            pixels[offset + 1] = int(green * alpha)
            pixels[offset + 2] = int(red * alpha)
            pixels[offset + 3] = int(255 * alpha)

    # AND mask left at zero: the alpha channel already carries the transparency.
    mask = bytes(size * 4)
    blob = bytes(header) + bytes(pixels) + mask
    buffer = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    return user32.CreateIconFromResourceEx(buffer, len(blob), True, 0x00030000, size, size, 0)
