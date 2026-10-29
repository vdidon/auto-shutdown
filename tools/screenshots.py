"""Produit les captures d'écran du README à partir des vraies fenêtres.

Chaque fenêtre est construite par le code de l'application, alimentée par un état
simulé : aucune tâche n'est réellement armée, rien ne peut endormir la machine.
Les images sont déposées dans `docs/images/`.

Le script affiche brièvement les fenêtres, ajoute une icône temporaire dans la
zone de notification et déplace le pointeur pour ouvrir le menu contextuel :
ne pas toucher à la souris pendant son exécution.

Usage :
    uv run --with pillow python tools/screenshots.py
"""

from __future__ import annotations

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
from auto_shutdown.power import Action
from auto_shutdown.scheduler import Snapshot, State
from auto_shutdown.ui import ConfigWindow, ReminderWindow, UiCallbacks, format_duration

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

#: Laisse au compositeur le temps de terminer l'animation d'ouverture.
SETTLE_SECONDS = 0.8

#: Rayon des coins arrondis des fenêtres Windows 11, en pixels logiques.
CORNER_RADIUS = 8

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")


def _callbacks(snapshot: Snapshot) -> UiCallbacks:
    return UiCallbacks(
        on_arm=lambda *_: None,
        on_cancel=lambda: None,
        on_postpone=lambda _: None,
        on_quit=lambda: None,
        snapshot=lambda: snapshot,
    )


def _frame_bounds(hwnd: int) -> tuple[int, int, int, int]:
    """Rectangle visible de la fenêtre, ombre portée exclue."""
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
    """Rend transparents les coins, où la capture montre le bureau."""
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *image.size), radius=radius, fill=255)
    image = image.convert("RGBA")
    image.putalpha(mask)
    return image


def _grab(bounds: tuple[int, int, int, int], name: str, *, rounded: bool) -> None:
    image = ImageGrab.grab(bbox=bounds, all_screens=True)
    if rounded:
        image = _round_corners(image, round(CORNER_RADIUS * _scale()))
    image.save(OUTPUT / name, optimize=True)
    print(f"{name} : {image.width}x{image.height}")


def _settle(root: tk.Tk) -> None:
    deadline = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)


def capture_windows(root: tk.Tk) -> None:
    config_window = ConfigWindow(root, Config(), _callbacks(ARMED))
    config_window._win.attributes("-topmost", True)
    _settle(root)
    hwnd = int(config_window._win.wm_frame(), 16)
    _grab(_frame_bounds(hwnd), "config.png", rounded=True)
    config_window.close()

    reminder = ReminderWindow(root, _callbacks(REMINDING), REMINDING)
    reminder._win.attributes("-topmost", True)
    _settle(root)
    hwnd = int(reminder._win.wm_frame(), 16)
    _grab(_frame_bounds(hwnd), "reminder.png", rounded=True)
    reminder.close()


def capture_tray_menu() -> None:
    """Ouvre le vrai menu contextuel du tray et le capture."""
    assert ARMED.action is not None
    status = f"{ARMED.action.value} dans {format_duration(ARMED.remaining)}"
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
        raise RuntimeError("Le tray n'a pas démarré")

    # Le menu s'ouvre sous le pointeur : le placer au centre de l'écran.
    user32.SetCursorPos(user32.GetSystemMetrics(0) // 2, user32.GetSystemMetrics(1) // 3)
    user32.PostMessageW(
        tray._hwnd,
        winapi.WM_TRAYICON,
        0,
        winapi.WM_RBUTTONUP,
    )

    menu = 0
    deadline = time.monotonic() + 5
    while not menu and time.monotonic() < deadline:
        time.sleep(0.05)
        menu = user32.FindWindowW("#32768", None)
    if not menu:
        tray.shutdown()
        raise RuntimeError("Le menu contextuel ne s'est pas ouvert")

    time.sleep(SETTLE_SECONDS)
    rect = wintypes.RECT()
    user32.GetWindowRect(menu, ctypes.byref(rect))
    _grab((rect.left, rect.top, rect.right, rect.bottom), "tray-menu.png", rounded=True)

    user32.PostMessageW(menu, WM_KEYDOWN, VK_ESCAPE, 0)
    time.sleep(0.2)
    tray.shutdown()
    thread.join(timeout=5)


def render_icons() -> None:
    """Icône de l'application et pastilles d'état, au rendu de `winapi.make_icon`."""
    # `Image.open` agrandirait la plus petite image du fichier : la version
    # 256 pixels est donc extraite explicitement.
    with asset_path(ICON_FILE).open("rb") as stream:
        icon = IcoImagePlugin.IcoFile(stream).getimage((256, 256))
        icon.convert("RGBA").save(OUTPUT / "icon.png", optimize=True)
    print("icon.png : 256x256")

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
        print(f"state-{name}.png : {size}x{size}")


def main() -> None:
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
