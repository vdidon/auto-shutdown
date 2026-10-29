"""Notification-area icon and Windows message loop.

A single window, hence a single message loop, receives both the notification
area events and the power notifications (`WM_POWERBROADCAST`). No
synchronization is needed between the two: a resume from sleep and a click on
the menu cannot be handled simultaneously.

The window is deliberately an ordinary, never-shown window rather than an
`HWND_MESSAGE` window: the latter cannot be brought to the foreground, which
prevents the context menu from closing when the user clicks elsewhere.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

from . import winapi
from .config import POSTPONE_CHOICES
from .i18n import tr

log = logging.getLogger(__name__)

WINDOW_CLASS = "AutoShutdownTrayWindow"
TRAY_ICON_ID = 1

# Context menu entry identifiers.
CMD_CONFIGURE = 1
CMD_CANCEL = 2
CMD_OPEN_LOG = 4
CMD_QUIT = 5

#: Base of the postpone submenu identifiers: the entry at index `i` gets the
#: identifier `CMD_POSTPONE_BASE + i`. Chosen high enough never to collide with
#: the fixed commands above.
CMD_POSTPONE_BASE = 100

#: Icon colors according to the task state.
COLOR_IDLE = (120, 140, 160)
COLOR_ARMED = (235, 150, 40)
COLOR_REMINDING = (220, 70, 60)


@dataclass(slots=True)
class TrayCallbacks:
    """Functions called by the tray, all from the window thread."""

    on_configure: Callable[[], None]
    on_cancel: Callable[[], None]
    #: Receives the postpone duration, in minutes.
    on_postpone: Callable[[int], None]
    on_open_log: Callable[[], None]
    on_quit: Callable[[], None]
    on_suspend: Callable[[], None]
    on_resume: Callable[[], None]
    #: Returns `(task armed?, status label)` to build the menu.
    query_state: Callable[[], tuple[bool, str]]


class Tray:
    """Notification-area icon driven from its own thread.

    `run()` creates the window and only returns on shutdown: it must therefore
    be called in a dedicated thread.
    """

    def __init__(self, callbacks: TrayCallbacks, tooltip: str = "Auto Shutdown") -> None:
        self._cb = callbacks
        self._hwnd: wintypes.HWND | None = None
        self._icons: dict[tuple[int, int, int], wintypes.HICON] = {}
        self._current_color = COLOR_IDLE
        self._tooltip = tooltip
        self._power_handle: wintypes.HANDLE | None = None
        self._taskbar_created_msg = 0
        self._ready = threading.Event()
        self._notify_lock = threading.Lock()
        # Windows keeps a reference to the window procedure for the whole life
        # of the class: without a Python reference it would be garbage-collected
        # and the next call would crash the process.
        self._wndproc = winapi.WNDPROC(self._on_message)

    # -- public API --------------------------------------------------------

    def run(self) -> None:
        """Create the window, add the icon, then pump messages."""
        self._create_window()
        self._register_power_notifications()
        self._add_icon()
        self._ready.set()
        self._pump()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def set_state(self, color: tuple[int, int, int], tooltip: str) -> None:
        """Update the icon and its tooltip. Callable from any thread."""
        self._current_color = color
        self._tooltip = tooltip
        self._modify_icon()

    def notify(self, title: str, message: str, *, warning: bool = False) -> None:
        """Show a system balloon notification. Callable from any thread."""
        if self._hwnd is None:
            return
        data = self._icon_data(winapi.NIF_INFO)
        data.szInfoTitle = title[:63]
        data.szInfo = message[:255]
        data.dwInfoFlags = winapi.NIIF_WARNING if warning else winapi.NIIF_INFO
        with self._notify_lock:
            winapi.shell32.Shell_NotifyIconW(winapi.NIM_MODIFY, ctypes.byref(data))

    def shutdown(self) -> None:
        """Request the window to close, from any thread.

        `DestroyWindow` is only valid on the thread that owns the window: the
        work is therefore delegated through a posted message.
        """
        if self._hwnd is not None:
            winapi.user32.PostMessageW(self._hwnd, winapi.WM_CLOSE, 0, 0)

    # -- construction ------------------------------------------------------

    def _create_window(self) -> None:
        hinstance = winapi.kernel32.GetModuleHandleW(None)
        wndclass = winapi.WNDCLASSW()
        wndclass.lpfnWndProc = self._wndproc
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = WINDOW_CLASS
        # An already registered class returns 0: harmless here, the next
        # window reuses the existing registration.
        winapi.user32.RegisterClassW(ctypes.byref(wndclass))

        self._hwnd = winapi.user32.CreateWindowExW(
            0,
            WINDOW_CLASS,
            "Auto Shutdown",
            winapi.WS_OVERLAPPED,
            winapi.CW_USEDEFAULT,
            winapi.CW_USEDEFAULT,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not self._hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowExW failed")

        # Re-register the icon if Windows Explorer restarts.
        self._taskbar_created_msg = winapi.user32.RegisterWindowMessageW("TaskbarCreated")

    def _register_power_notifications(self) -> None:
        """Subscribe to sleep/resume transitions.

        Essential: a window that is never shown does not receive
        `WM_POWERBROADCAST` broadcasts by default, so it must subscribe
        explicitly.
        """
        self._power_handle = winapi.user32.RegisterSuspendResumeNotification(
            self._hwnd, winapi.DEVICE_NOTIFY_WINDOW_HANDLE
        )
        if not self._power_handle:
            log.error(
                "RegisterSuspendResumeNotification failed (code %d): "
                "automatic cancellation on resume from sleep is inoperative",
                ctypes.get_last_error(),
            )

    def _icon_handle(self, color: tuple[int, int, int]) -> wintypes.HICON:
        if color not in self._icons:
            self._icons[color] = winapi.make_icon(color)
        return self._icons[color]

    def _icon_data(self, flags: int) -> winapi.NOTIFYICONDATAW:
        data = winapi.NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(winapi.NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = TRAY_ICON_ID
        data.uFlags = flags
        data.uCallbackMessage = winapi.WM_TRAYICON
        data.hIcon = self._icon_handle(self._current_color)
        data.szTip = self._tooltip[:127]
        return data

    def _add_icon(self) -> None:
        data = self._icon_data(winapi.NIF_MESSAGE | winapi.NIF_ICON | winapi.NIF_TIP)
        with self._notify_lock:
            if not winapi.shell32.Shell_NotifyIconW(winapi.NIM_ADD, ctypes.byref(data)):
                raise OSError(ctypes.get_last_error(), "Shell_NotifyIconW(NIM_ADD) failed")

    def _modify_icon(self) -> None:
        if self._hwnd is None:
            return
        data = self._icon_data(winapi.NIF_ICON | winapi.NIF_TIP)
        with self._notify_lock:
            winapi.shell32.Shell_NotifyIconW(winapi.NIM_MODIFY, ctypes.byref(data))

    def _remove_icon(self) -> None:
        if self._hwnd is None:
            return
        data = winapi.NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(winapi.NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = TRAY_ICON_ID
        with self._notify_lock:
            winapi.shell32.Shell_NotifyIconW(winapi.NIM_DELETE, ctypes.byref(data))

    # -- message loop ------------------------------------------------------

    def _pump(self) -> None:
        msg = winapi.MSG()
        while True:
            result = winapi.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:  # WM_QUIT
                break
            if result == -1:
                log.error("GetMessageW failed (code %d)", ctypes.get_last_error())
                break
            winapi.user32.TranslateMessage(ctypes.byref(msg))
            winapi.user32.DispatchMessageW(ctypes.byref(msg))

    def _on_message(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        # ctypes converts the simple types of the WNDPROC signature to Python
        # integers: the parameters are therefore annotated `int`, not `wintypes.*`.
        try:
            handled = self._dispatch(msg, wparam, lparam)
        except Exception:
            # An exception escaping a window procedure leaves Windows in an
            # undefined state: it is logged and swallowed.
            log.exception("Error while handling message 0x%04X", msg)
            handled = None
        if handled is not None:
            return handled
        return winapi.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _dispatch(  # noqa: PLR0911  (dispatch: one return per handled message)
        self, msg: int, wparam: int, lparam: int
    ) -> int | None:
        if msg == winapi.WM_TRAYICON:
            self._on_tray_event(lparam)
            return 0

        if msg == winapi.WM_COMMAND:
            self._on_command(wparam & 0xFFFF)
            return 0

        if msg == winapi.WM_POWERBROADCAST:
            return self._on_power_event(wparam)

        if msg == self._taskbar_created_msg and self._taskbar_created_msg:
            log.info("Explorer restarted: re-adding the icon")
            self._add_icon()
            return 0

        if msg == winapi.WM_CLOSE:
            self._cleanup()
            winapi.user32.DestroyWindow(self._hwnd)
            return 0

        if msg == winapi.WM_DESTROY:
            winapi.user32.PostQuitMessage(0)
            return 0

        return None

    def _on_power_event(self, event: int) -> int:
        if event == winapi.PBT_APMSUSPEND:
            self._cb.on_suspend()
        elif event in (winapi.PBT_APMRESUMESUSPEND, winapi.PBT_APMRESUMEAUTOMATIC):
            # Both events often arrive back to back for a single resume;
            # downstream handling must therefore be idempotent.
            self._cb.on_resume()
        return 1  # TRUE: message handled.

    def _on_tray_event(self, mouse_msg: int) -> None:
        if mouse_msg in (winapi.WM_LBUTTONUP, winapi.WM_LBUTTONDBLCLK):
            self._cb.on_configure()
        elif mouse_msg == winapi.WM_RBUTTONUP:
            self._show_menu()

    def _on_command(self, command: int) -> None:
        index = command - CMD_POSTPONE_BASE
        if 0 <= index < len(POSTPONE_CHOICES):
            self._cb.on_postpone(POSTPONE_CHOICES[index])
            return

        handlers = {
            CMD_CONFIGURE: self._cb.on_configure,
            CMD_CANCEL: self._cb.on_cancel,
            CMD_OPEN_LOG: self._cb.on_open_log,
            CMD_QUIT: self._cb.on_quit,
        }
        handler = handlers.get(command)
        if handler is not None:
            handler()

    def _show_menu(self) -> None:
        armed, status = self._cb.query_state()
        menu = winapi.user32.CreatePopupMenu()
        if not menu:
            return
        try:
            winapi.user32.AppendMenuW(menu, winapi.MF_STRING | winapi.MF_GRAYED, 0, status)
            winapi.user32.AppendMenuW(menu, winapi.MF_SEPARATOR, 0, None)
            winapi.user32.AppendMenuW(menu, winapi.MF_STRING, CMD_CONFIGURE, tr("menu.configure"))
            flags = winapi.MF_STRING if armed else winapi.MF_STRING | winapi.MF_GRAYED
            # The submenu is attached to the main menu: `DestroyMenu` on the
            # latter also frees it, so no separate cleanup is required.
            submenu = winapi.user32.CreatePopupMenu()
            if submenu:
                for index, minutes in enumerate(POSTPONE_CHOICES):
                    winapi.user32.AppendMenuW(
                        submenu,
                        winapi.MF_STRING,
                        CMD_POSTPONE_BASE + index,
                        tr("menu.postpone_choice", minutes=minutes),
                    )
                winapi.user32.AppendMenuW(
                    menu, flags | winapi.MF_POPUP, submenu, tr("menu.postpone")
                )
            winapi.user32.AppendMenuW(menu, flags, CMD_CANCEL, tr("menu.cancel"))
            winapi.user32.AppendMenuW(menu, winapi.MF_SEPARATOR, 0, None)
            winapi.user32.AppendMenuW(menu, winapi.MF_STRING, CMD_OPEN_LOG, tr("menu.open_log"))
            winapi.user32.AppendMenuW(menu, winapi.MF_STRING, CMD_QUIT, tr("menu.quit"))

            point = winapi.POINT()
            winapi.user32.GetCursorPos(ctypes.byref(point))
            # Bring the window to the foreground before showing the menu,
            # otherwise it stays open when the user clicks elsewhere.
            winapi.user32.SetForegroundWindow(self._hwnd)
            command = winapi.user32.TrackPopupMenu(
                menu,
                winapi.TPM_RIGHTBUTTON | winapi.TPM_RETURNCMD,
                point.x,
                point.y,
                0,
                self._hwnd,
                None,
            )
            # Neutral message required by the documentation so the menu
            # closes cleanly after the selection.
            winapi.user32.PostMessageW(self._hwnd, winapi.WM_NULL, 0, 0)
            if command:
                self._on_command(int(command))
        finally:
            winapi.user32.DestroyMenu(menu)

    def _cleanup(self) -> None:
        self._remove_icon()
        if self._power_handle:
            winapi.user32.UnregisterSuspendResumeNotification(self._power_handle)
            self._power_handle = None
        for icon in self._icons.values():
            winapi.user32.DestroyIcon(icon)
        self._icons.clear()
