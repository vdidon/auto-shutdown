"""Icône de notification et boucle de messages Windows.

Une seule fenêtre, donc une seule boucle de messages, reçoit à la fois les
événements de la zone de notification et les notifications d'alimentation
(`WM_POWERBROADCAST`). Aucune synchronisation n'est nécessaire entre les deux :
un retour de veille et un clic sur le menu ne peuvent pas être traités
simultanément.

La fenêtre est délibérément une fenêtre ordinaire jamais affichée plutôt qu'une
fenêtre `HWND_MESSAGE` : ces dernières ne peuvent pas passer au premier plan, ce
qui empêche le menu contextuel de se refermer quand on clique ailleurs.
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

log = logging.getLogger(__name__)

WINDOW_CLASS = "AutoShutdownTrayWindow"
TRAY_ICON_ID = 1

# Identifiants des entrées du menu contextuel.
CMD_CONFIGURE = 1
CMD_CANCEL = 2
CMD_OPEN_LOG = 4
CMD_QUIT = 5

#: Base des identifiants du sous-menu de report : l'entrée d'indice `i` porte
#: l'identifiant `CMD_POSTPONE_BASE + i`. Choisie assez haut pour ne jamais
#: entrer en collision avec les commandes fixes ci-dessus.
CMD_POSTPONE_BASE = 100

#: Couleurs de l'icône selon l'état de la tâche.
COLOR_IDLE = (120, 140, 160)
COLOR_ARMED = (235, 150, 40)
COLOR_REMINDING = (220, 70, 60)


@dataclass(slots=True)
class TrayCallbacks:
    """Fonctions appelées par le tray, toutes depuis le thread de la fenêtre."""

    on_configure: Callable[[], None]
    on_cancel: Callable[[], None]
    #: Reçoit la durée du report, en minutes.
    on_postpone: Callable[[int], None]
    on_open_log: Callable[[], None]
    on_quit: Callable[[], None]
    on_suspend: Callable[[], None]
    on_resume: Callable[[], None]
    #: Renvoie `(tâche armée ?, libellé d'état)` pour construire le menu.
    query_state: Callable[[], tuple[bool, str]]


class Tray:
    """Icône de notification pilotée depuis son propre thread.

    `run()` crée la fenêtre puis ne rend la main qu'à l'arrêt : il doit donc
    être appelé dans un thread dédié.
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
        # La fonction de fenêtre est référencée par Windows pendant toute la vie
        # de la classe : sans référence Python, elle serait ramassée par le GC
        # et l'appel suivant planterait le processus.
        self._wndproc = winapi.WNDPROC(self._on_message)

    # -- API publique ------------------------------------------------------

    def run(self) -> None:
        """Crée la fenêtre, ajoute l'icône, puis pompe les messages."""
        self._create_window()
        self._register_power_notifications()
        self._add_icon()
        self._ready.set()
        self._pump()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def set_state(self, color: tuple[int, int, int], tooltip: str) -> None:
        """Met à jour l'icône et son infobulle. Appelable depuis tout thread."""
        self._current_color = color
        self._tooltip = tooltip
        self._modify_icon()

    def notify(self, title: str, message: str, *, warning: bool = False) -> None:
        """Affiche une info-bulle système. Appelable depuis tout thread."""
        if self._hwnd is None:
            return
        data = self._icon_data(winapi.NIF_INFO)
        data.szInfoTitle = title[:63]
        data.szInfo = message[:255]
        data.dwInfoFlags = winapi.NIIF_WARNING if warning else winapi.NIIF_INFO
        with self._notify_lock:
            winapi.shell32.Shell_NotifyIconW(winapi.NIM_MODIFY, ctypes.byref(data))

    def shutdown(self) -> None:
        """Demande la fermeture de la fenêtre depuis n'importe quel thread.

        `DestroyWindow` n'est valide que dans le thread propriétaire de la
        fenêtre : le travail est donc délégué via un message posté.
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
        # Une classe déjà enregistrée renvoie 0 : sans conséquence ici, la
        # fenêtre suivante réutilise l'enregistrement existant.
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
            raise OSError(ctypes.get_last_error(), "CreateWindowExW a échoué")

        # Réenregistrement de l'icône si l'explorateur Windows redémarre.
        self._taskbar_created_msg = winapi.user32.RegisterWindowMessageW("TaskbarCreated")

    def _register_power_notifications(self) -> None:
        """S'abonne aux transitions veille/reprise.

        Indispensable : une fenêtre non affichée ne reçoit pas les diffusions
        `WM_POWERBROADCAST` par défaut, il faut s'y abonner explicitement.
        """
        self._power_handle = winapi.user32.RegisterSuspendResumeNotification(
            self._hwnd, winapi.DEVICE_NOTIFY_WINDOW_HANDLE
        )
        if not self._power_handle:
            log.error(
                "RegisterSuspendResumeNotification a échoué (code %d) : "
                "l'annulation automatique au retour de veille est inopérante",
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
                raise OSError(ctypes.get_last_error(), "Shell_NotifyIconW(NIM_ADD) a échoué")

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

    # -- boucle de messages ------------------------------------------------

    def _pump(self) -> None:
        msg = winapi.MSG()
        while True:
            result = winapi.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0:  # WM_QUIT
                break
            if result == -1:
                log.error("GetMessageW a échoué (code %d)", ctypes.get_last_error())
                break
            winapi.user32.TranslateMessage(ctypes.byref(msg))
            winapi.user32.DispatchMessageW(ctypes.byref(msg))

    def _on_message(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        # ctypes convertit les types simples de la signature WNDPROC en entiers
        # Python : les paramètres sont donc annotés `int`, pas `wintypes.*`.
        try:
            handled = self._dispatch(msg, wparam, lparam)
        except Exception:
            # Une exception qui traverse une fonction de fenêtre laisse Windows
            # dans un état indéfini : elle est journalisée et absorbée.
            log.exception("Erreur lors du traitement du message 0x%04X", msg)
            handled = None
        if handled is not None:
            return handled
        return winapi.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _dispatch(  # noqa: PLR0911  (aiguillage : un retour par message traité)
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
            log.info("Explorateur redémarré : réinsertion de l'icône")
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
            # Les deux événements arrivent souvent à la suite pour une même
            # reprise ; le traitement en aval doit donc être idempotent.
            self._cb.on_resume()
        return 1  # TRUE : message traité.

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
            winapi.user32.AppendMenuW(menu, winapi.MF_STRING, CMD_CONFIGURE, "Configurer et armer…")
            flags = winapi.MF_STRING if armed else winapi.MF_STRING | winapi.MF_GRAYED
            # Le sous-menu est rattaché au menu principal : `DestroyMenu` sur ce
            # dernier libère aussi celui-ci, aucun nettoyage séparé n'est requis.
            submenu = winapi.user32.CreatePopupMenu()
            if submenu:
                for index, minutes in enumerate(POSTPONE_CHOICES):
                    winapi.user32.AppendMenuW(
                        submenu,
                        winapi.MF_STRING,
                        CMD_POSTPONE_BASE + index,
                        f"{minutes} minutes",
                    )
                winapi.user32.AppendMenuW(menu, flags | winapi.MF_POPUP, submenu, "Reporter de")
            winapi.user32.AppendMenuW(menu, flags, CMD_CANCEL, "Annuler la tâche")
            winapi.user32.AppendMenuW(menu, winapi.MF_SEPARATOR, 0, None)
            winapi.user32.AppendMenuW(menu, winapi.MF_STRING, CMD_OPEN_LOG, "Ouvrir le journal")
            winapi.user32.AppendMenuW(menu, winapi.MF_STRING, CMD_QUIT, "Quitter")

            point = winapi.POINT()
            winapi.user32.GetCursorPos(ctypes.byref(point))
            # Passer au premier plan avant d'afficher le menu, faute de quoi
            # celui-ci reste ouvert lorsque l'utilisateur clique ailleurs.
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
            # Message neutre exigé par la documentation pour que le menu se
            # referme proprement après la sélection.
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
