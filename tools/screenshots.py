"""Produce the README screenshots from the real windows.

Each window is built by the application's own code, fed with a simulated
state: no task is actually armed, nothing can put the machine to sleep.
The images are written to `docs/images/`.

The script briefly shows the windows, adds a temporary icon to the
notification area and moves the pointer to open the context menu:
do not touch the mouse while it runs.

Usage:
    uv run --with pillow python tools/screenshots.py [--language {en,fr}]

`--language` selects the interface language of the captured windows
(default: `en`, matching the README). Window captures are suffixed with the
language (`config-en.png`), so capturing another language never overwrites
the images the README shows.
"""

from __future__ import annotations

import argparse
import ctypes
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from PIL import IcoImagePlugin, Image, ImageDraw, ImageGrab

from auto_shutdown import tray as tray_module
from auto_shutdown import winapi
from auto_shutdown.app import _enable_dpi_awareness
from auto_shutdown.config import ICON_FILE, Config, asset_path
from auto_shutdown.i18n import CATALOGS, language, set_language
from auto_shutdown.power import Action
from auto_shutdown.scheduler import Snapshot, State
from auto_shutdown.ui import ConfigWindow, ReminderWindow, UiCallbacks, status_text

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "images"

ARMED = Snapshot(
    state=State.ARMED, action=Action.HIBERNATE, remaining=1477.0, reminder_active=False
)
REMINDING = Snapshot(
    state=State.REMINDING, action=Action.HIBERNATE, remaining=263.0, reminder_active=True
)

DWMWA_EXTENDED_FRAME_BOUNDS = 9
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002

MENU_ATTEMPTS = 3

#: Gives the compositor time to finish the opening animation.
SETTLE_SECONDS = 0.8

#: Radius of the rounded corners of Windows 11 windows, in logical pixels.
CORNER_RADIUS = 8

#: Lets `PrintWindow` capture DWM-composed content, title bar included.
PW_RENDERFULLCONTENT = 0x2

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
dwmapi = ctypes.WinDLL("dwmapi")

user32.GetWindowDC.argtypes = (wintypes.HWND,)
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
user32.PrintWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.GetDIBits.argtypes = (
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
)
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteDC.argtypes = (wintypes.HDC,)


def _callbacks(snapshot: Snapshot) -> UiCallbacks:
    return UiCallbacks(
        on_arm=lambda *_: None,
        on_cancel=lambda: None,
        on_postpone=lambda _: None,
        on_quit=lambda: None,
        snapshot=lambda: snapshot,
    )


def _frame_bounds(hwnd: int) -> tuple[int, int, int, int]:
    """Visible rectangle of the window, drop shadow excluded."""
    rect = wintypes.RECT()
    dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    return rect.left, rect.top, rect.right, rect.bottom


def _scale() -> float:
    return user32.GetDpiForSystem() / 96


def _round_corners(image: Image.Image, radius: int) -> Image.Image:
    """Make the corners transparent, where the capture shows the desktop."""
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *image.size), radius=radius, fill=255)
    image = image.convert("RGBA")
    image.putalpha(mask)
    return image


def _save(image: Image.Image, name: str) -> None:
    image = _round_corners(image, round(CORNER_RADIUS * _scale()))
    image.save(OUTPUT / name, optimize=True)
    print(f"{name}: {image.width}x{image.height}")


def _print_window(hwnd: int) -> Image.Image:
    """Render the window itself, title bar included, whatever lies behind it.

    A plain screen grab would pick up the desktop through the translucent
    Windows 11 title bar; `PrintWindow` asks DWM for the window's own pixels.
    """
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    try:
        gdi32.SelectObject(memory_dc, bitmap)
        if not user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT):
            raise OSError(ctypes.get_last_error(), "PrintWindow failed")
        # Negative height: rows top to bottom, as Pillow expects them.
        header = winapi.BITMAPINFOHEADER(
            biSize=ctypes.sizeof(winapi.BITMAPINFOHEADER),
            biWidth=width,
            biHeight=-height,
            biPlanes=1,
            biBitCount=32,
        )
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(header), 0)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
    image = Image.frombuffer("RGB", (width, height), bytes(pixels), "raw", "BGRX", 0, 1)
    # The window rectangle includes invisible resize borders: keep the visible frame.
    left, top, right, bottom = _frame_bounds(hwnd)
    return image.crop((left - rect.left, top - rect.top, right - rect.left, bottom - rect.top))


def _settle(root: tk.Tk) -> None:
    deadline = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)


def _activate(hwnd: int) -> None:
    """Bring the window to the foreground so its title bar is drawn as active.

    Windows refuses `SetForegroundWindow` to a process that did not receive the
    last input event; a synthetic Alt press lifts that restriction.
    """
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)


def _capture(root: tk.Tk, window: tk.Toplevel, name: str) -> None:
    window.attributes("-topmost", True)
    hwnd = int(window.wm_frame(), 16)
    _settle(root)
    _activate(hwnd)
    _settle(root)
    _save(_print_window(hwnd), name)


def capture_windows(root: tk.Tk) -> None:
    config_window = ConfigWindow(root, Config(), _callbacks(ARMED))
    _capture(root, config_window._win, f"config-{language()}.png")
    config_window.close()

    reminder = ReminderWindow(root, _callbacks(REMINDING), REMINDING)
    _capture(root, reminder._win, f"reminder-{language()}.png")
    reminder.close()


def _wait_for_menu(timeout: float = 5.0) -> int:
    """Handle of the open popup menu, or 0 if none appears in time.

    Hidden windows of the menu class (`#32768`) can linger in the session: only
    a visible one with a non-empty rectangle is the menu just opened.
    """
    deadline = time.monotonic() + timeout
    rect = wintypes.RECT()
    while time.monotonic() < deadline:
        time.sleep(0.05)
        menu = user32.FindWindowW("#32768", None)
        while menu:
            user32.GetWindowRect(menu, ctypes.byref(rect))
            if user32.IsWindowVisible(menu) and rect.right > rect.left:
                return menu
            menu = user32.FindWindowExW(None, menu, "#32768", None)
    return 0


def capture_tray_menu() -> None:
    """Open the real tray context menu and capture it."""
    status = status_text(ARMED)
    tray = tray_module.Tray(
        tray_module.TrayCallbacks(
            on_configure=lambda: None,
            on_cancel=lambda: None,
            on_postpone=lambda _: None,
            on_open_log=lambda: None,
            on_quit=lambda: None,
            on_suspend=lambda: None,
            on_resume=lambda: None,
            query_state=lambda: (True, status),
        )
    )
    thread = threading.Thread(target=tray.run, daemon=True)
    thread.start()
    if not tray.wait_ready():
        raise RuntimeError("The tray did not start")

    try:
        for _ in range(MENU_ATTEMPTS):
            image = _open_and_grab_menu(tray)
            if image is not None:
                # Menus are opaque: a screen grab is faithful, unlike for windows.
                _save(image, f"tray-menu-{language()}.png")
                return
        raise RuntimeError("The context menu did not stay open long enough to be captured")
    finally:
        tray.shutdown()
        thread.join(timeout=5)


def _open_and_grab_menu(tray: tray_module.Tray) -> Image.Image | None:
    """One attempt; `None` if the menu closed before the capture.

    The menu closes as soon as the tray window loses the foreground, which
    Windows may refuse to give it: the same synthetic Alt press as for the
    windows grants it.
    """
    # The menu opens under the pointer: put it at the centre of the screen.
    user32.SetCursorPos(user32.GetSystemMetrics(0) // 2, user32.GetSystemMetrics(1) // 3)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.PostMessageW(tray._hwnd, winapi.WM_TRAYICON, 0, winapi.WM_RBUTTONUP)

    menu = _wait_for_menu()
    if not menu:
        return None
    time.sleep(SETTLE_SECONDS)
    rect = wintypes.RECT()
    user32.GetWindowRect(menu, ctypes.byref(rect))
    if not user32.IsWindowVisible(menu) or rect.right <= rect.left:
        return None
    image = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
    user32.PostMessageW(menu, WM_KEYDOWN, VK_ESCAPE, 0)
    time.sleep(0.2)
    return image


def render_icons() -> None:
    """Application icon and status dots, rendered like `winapi.make_icon`."""
    # `Image.open` would upscale the smallest image in the file: the 256-pixel
    # version is therefore extracted explicitly.
    with asset_path(ICON_FILE).open("rb") as stream:
        icon = IcoImagePlugin.IcoFile(stream).getimage((256, 256))
        icon.convert("RGBA").save(OUTPUT / "icon.png", optimize=True)
    print("icon.png: 256x256")

    size = 64
    supersample = 4
    states = {
        "idle": tray_module.COLOR_IDLE,
        "armed": tray_module.COLOR_ARMED,
        "reminding": tray_module.COLOR_REMINDING,
    }
    for name, color in states.items():
        big = size * supersample
        image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        margin = round(1.5 * supersample * size / 32)
        ImageDraw.Draw(image).ellipse((margin, margin, big - margin, big - margin), fill=color)
        image.resize((size, size), Image.Resampling.LANCZOS).save(
            OUTPUT / f"state-{name}.png", optimize=True
        )
        print(f"state-{name}.png: {size}x{size}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture the README screenshots.")
    parser.add_argument(
        "--language",
        choices=sorted(CATALOGS),
        default="en",
        help="interface language of the captured windows (default: en, matching the README)",
    )
    set_language(parser.parse_args().language)

    _enable_dpi_awareness()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    root = tk.Tk()
    root.withdraw()
    root.iconbitmap(default=str(asset_path(ICON_FILE)))
    try:
        capture_windows(root)
    finally:
        root.destroy()

    capture_tray_menu()
    render_icons()


if __name__ == "__main__":
    main()
