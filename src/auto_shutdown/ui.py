"""Interface tkinter : fenêtre de configuration et fenêtre de rappel.

Tkinter n'est pilotable que depuis le thread qui a créé sa fenêtre racine. Cette
racine vit donc dans le thread principal et toute demande venue du tray ou de
l'ordonnanceur passe par `Ui.call`, qui réachemine l'appel via `after`.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from . import __version__
from .config import (
    ICON_FILE,
    MAX_DELAY_MINUTES,
    MIN_DELAY_MINUTES,
    POSTPONE_CHOICES,
    Config,
    asset_path,
)
from .power import Action
from .scheduler import Snapshot

log = logging.getLogger(__name__)


def format_duration(seconds: float) -> str:
    """Formate une durée en `HH:MM:SS`, arrondie à la seconde supérieure."""
    total = max(0, int(seconds + 0.5))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass(slots=True)
class UiCallbacks:
    """Actions déclenchées par l'interface."""

    #: `(action, délai en minutes, avance du rappel en minutes)`
    on_arm: Callable[[Action, int, int], None]
    on_cancel: Callable[[], None]
    on_postpone: Callable[[int], None]
    on_quit: Callable[[], None]
    snapshot: Callable[[], Snapshot]


class Ui:
    """Racine tkinter et fenêtres de l'application."""

    def __init__(self, config: Config, callbacks: UiCallbacks) -> None:
        self._config = config
        self._cb = callbacks
        self._root = tk.Tk()
        self._root.withdraw()
        self._apply_icon()
        # Fermer la dernière fenêtre ne doit pas arrêter l'application : elle
        # continue de vivre dans la zone de notification.
        self._root.protocol("WM_DELETE_WINDOW", lambda: None)
        self._config_window: ConfigWindow | None = None
        self._reminder_window: ReminderWindow | None = None

    # -- cycle de vie ------------------------------------------------------

    def run(self) -> None:
        """Boucle principale ; ne rend la main qu'à l'arrêt de l'application."""
        self._root.mainloop()

    def call(self, fn: Callable[..., None], *args: object) -> None:
        """Exécute `fn` dans le thread de l'interface. Appelable de partout."""
        try:
            self._root.after(0, lambda: self._guarded(fn, *args))
        except RuntimeError:
            # La racine est déjà détruite : l'application s'arrête.
            log.debug("Appel d'interface ignoré, racine détruite")

    def quit(self) -> None:
        self.call(self._root.destroy)

    def _apply_icon(self) -> None:
        """Applique l'icône de l'application à toutes les fenêtres.

        `default=` la propage aux `Toplevel` créées ensuite. Son absence n'est
        pas une erreur : seule l'icône générique de Tk s'affiche alors.
        """
        icon = asset_path(ICON_FILE)
        if not icon.is_file():
            # L'icône est versionnée et embarquée dans l'exécutable : son
            # absence signale un défaut d'assemblage, pas une situation normale.
            log.warning("Icône introuvable : %s", icon)
            return
        try:
            self._root.iconbitmap(default=str(icon))
        except tk.TclError:
            log.warning("Icône refusée par Tk : %s", icon)
        else:
            log.debug("Icône appliquée : %s", icon)

    @staticmethod
    def _guarded(fn: Callable[..., None], *args: object) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("Erreur dans une fonction d'interface")

    # -- fenêtres ----------------------------------------------------------

    def show_config(self) -> None:
        if self._config_window is not None and self._config_window.alive:
            self._config_window.focus()
            return
        self._config_window = ConfigWindow(self._root, self._config, self._cb)
        # Sans cela, la fenêtre naît derrière celles déjà ouvertes — notamment
        # au lancement, où rien n'a encore attiré l'attention vers elle.
        self._config_window.focus()

    def show_reminder(self, snapshot: Snapshot) -> None:
        if self._reminder_window is not None and self._reminder_window.alive:
            return
        self._reminder_window = ReminderWindow(self._root, self._cb, snapshot)

    def close_reminder(self) -> None:
        if self._reminder_window is not None:
            self._reminder_window.close()
            self._reminder_window = None

    def refresh(self) -> None:
        """Rafraîchit le compte à rebours des fenêtres ouvertes."""
        if self._config_window is not None and self._config_window.alive:
            self._config_window.refresh_status()


class ConfigWindow:
    """Choix de l'action, du délai et du rappel, puis armement."""

    def __init__(self, root: tk.Tk, config: Config, callbacks: UiCallbacks) -> None:
        self._config = config
        self._cb = callbacks
        self.alive = True

        self._win = tk.Toplevel(root)
        self._win.title("Auto Shutdown")
        self._win.resizable(width=False, height=False)
        self._win.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self._win, padding=16)
        frame.grid(sticky="nsew")

        ttk.Label(frame, text="Action à exécuter").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._action_var = tk.StringVar(value=Action.parse(config.action).value)
        self._action_box = ttk.Combobox(
            frame,
            textvariable=self._action_var,
            values=[a.value for a in Action],
            state="readonly",
            width=28,
        )
        self._action_box.grid(row=1, column=0, columnspan=3, sticky="we", pady=(0, 12))

        ttk.Label(frame, text="À partir de maintenant, dans").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )

        delay = config.clamped_delay()
        self._hours_var = tk.StringVar(value=str(delay // 60))
        self._minutes_var = tk.StringVar(value=str(delay % 60))

        delay_row = ttk.Frame(frame)
        delay_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Spinbox(
            delay_row, from_=0, to=167, width=5, textvariable=self._hours_var, wrap=False
        ).grid(row=0, column=0)
        ttk.Label(delay_row, text="heure(s)").grid(row=0, column=1, padx=(6, 16))
        ttk.Spinbox(
            delay_row, from_=0, to=59, width=5, textvariable=self._minutes_var, wrap=False
        ).grid(row=0, column=2)
        ttk.Label(delay_row, text="minute(s)").grid(row=0, column=3, padx=(6, 0))

        self._reminder_var = tk.BooleanVar(value=config.reminder_enabled)
        self._reminder_minutes_var = tk.StringVar(value=str(config.reminder_minutes))
        reminder_row = ttk.Frame(frame)
        reminder_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Checkbutton(
            reminder_row,
            text="Me prévenir",
            variable=self._reminder_var,
            command=self._sync_reminder_state,
        ).grid(row=0, column=0)
        self._reminder_spin = ttk.Spinbox(
            reminder_row, from_=1, to=120, width=5, textvariable=self._reminder_minutes_var
        )
        self._reminder_spin.grid(row=0, column=1, padx=(6, 6))
        ttk.Label(reminder_row, text="minute(s) avant").grid(row=0, column=2)
        self._sync_reminder_state()

        self._status_var = tk.StringVar(value="")
        ttk.Separator(frame, orient="horizontal").grid(
            row=5, column=0, columnspan=3, sticky="we", pady=12
        )
        ttk.Label(frame, textvariable=self._status_var).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=3, sticky="e")
        ttk.Button(buttons, text="Fermer", command=self.close).grid(row=0, column=0, padx=(0, 8))
        self._cancel_button = ttk.Button(buttons, text="Annuler la tâche", command=self._on_cancel)
        self._cancel_button.grid(row=0, column=1, padx=(0, 8))
        ttk.Button(buttons, text="Démarrer", command=self._on_start).grid(row=0, column=2)

        self._error_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._error_var, foreground="#c0392b").grid(
            row=8, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        # Discret mais toujours visible : lever l'ambiguïté sur la version
        # réellement lancée, notamment entre un exécutable et les sources.
        ttk.Label(
            frame,
            text=f"version {__version__}",
            font=("Segoe UI", 8),
            foreground="#8a9099",
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(14, 0))

        self.refresh_status()
        self._centre(root)
        self._win.after(1000, self._tick)

    # -- événements --------------------------------------------------------

    def _sync_reminder_state(self) -> None:
        self._reminder_spin.state(["!disabled"] if self._reminder_var.get() else ["disabled"])

    def _read_delay(self) -> int | None:
        """Lit le délai saisi ; renvoie `None` et affiche l'erreur si invalide."""
        try:
            hours = int(self._hours_var.get())
            minutes = int(self._minutes_var.get())
        except ValueError:
            self._error_var.set("Le délai doit être un nombre entier.")
            return None
        total = hours * 60 + minutes
        if total < MIN_DELAY_MINUTES:
            self._error_var.set("Le délai doit valoir au moins une minute.")
            return None
        if total > MAX_DELAY_MINUTES:
            self._error_var.set("Le délai ne peut pas dépasser sept jours.")
            return None
        return total

    def _read_reminder(self, delay: int) -> int:
        if not self._reminder_var.get():
            return 0
        try:
            minutes = int(self._reminder_minutes_var.get())
        except ValueError:
            return 0
        # Un rappel qui tomberait à l'échéance ou après ne servirait à rien.
        return max(0, min(minutes, delay - 1))

    def _on_start(self) -> None:
        delay = self._read_delay()
        if delay is None:
            return
        self._error_var.set("")
        action = next(a for a in Action if a.value == self._action_var.get())
        reminder = self._read_reminder(delay)

        self._config.action = action.name
        self._config.delay_minutes = delay
        self._config.reminder_enabled = self._reminder_var.get()
        if reminder:
            self._config.reminder_minutes = reminder
        self._config.save()

        self._cb.on_arm(action, delay, reminder)
        self.refresh_status()

    def _on_cancel(self) -> None:
        self._cb.on_cancel()
        self.refresh_status()

    def _tick(self) -> None:
        if not self.alive:
            return
        self.refresh_status()
        self._win.after(1000, self._tick)

    def refresh_status(self) -> None:
        if not self.alive:
            return
        snapshot = self._cb.snapshot()
        if snapshot.armed and snapshot.action is not None:
            self._status_var.set(
                f"{snapshot.action.value} dans {format_duration(snapshot.remaining)}"
            )
            self._cancel_button.state(["!disabled"])
        else:
            self._status_var.set("Aucune tâche programmée.")
            self._cancel_button.state(["disabled"])

    def focus(self) -> None:
        self._win.deiconify()
        self._win.lift()
        self._win.focus_force()

    def close(self) -> None:
        self.alive = False
        self._win.destroy()

    def _centre(self, root: tk.Tk) -> None:
        self._win.update_idletasks()
        width = self._win.winfo_width()
        height = self._win.winfo_height()
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 3
        self._win.geometry(f"+{x}+{y}")


class ReminderWindow:
    """Avertissement affiché avant l'échéance, avec annulation et report."""

    def __init__(self, root: tk.Tk, callbacks: UiCallbacks, snapshot: Snapshot) -> None:
        self._cb = callbacks
        self.alive = True

        self._win = tk.Toplevel(root)
        self._win.title("Auto Shutdown — rappel")
        self._win.resizable(width=False, height=False)
        self._win.attributes("-topmost", True)
        self._win.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(self._win, padding=20)
        frame.grid()

        label = snapshot.action.value if snapshot.action else "L'action programmée"
        ttk.Label(frame, text=f"{label} dans", font=("Segoe UI", 11)).grid(row=0, column=0)

        self._countdown_var = tk.StringVar(value=format_duration(snapshot.remaining))
        ttk.Label(frame, textvariable=self._countdown_var, font=("Segoe UI", 26, "bold")).grid(
            row=1, column=0, pady=(4, 16)
        )

        postpone = ttk.Frame(frame)
        postpone.grid(row=2, column=0, pady=(0, 12))
        ttk.Label(postpone, text="Reporter de").grid(row=0, column=0, padx=(0, 8))
        for index, minutes in enumerate(POSTPONE_CHOICES):
            # `minutes=minutes` fige la valeur : sans cela, les quatre boutons
            # partageraient la dernière valeur de la boucle.
            ttk.Button(
                postpone,
                text=f"{minutes} min",
                width=7,
                command=lambda minutes=minutes: self._on_postpone(minutes),
            ).grid(row=0, column=index + 1, padx=2)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0)
        ttk.Button(buttons, text="Annuler", command=self._on_cancel).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Laisser faire", command=self.close).grid(row=0, column=1, padx=4)

        self._centre(root)
        # La fenêtre attire l'attention une fois, puis cesse de passer devant
        # les autres pour ne pas gêner un travail en cours.
        self._win.focus_force()
        self._win.after(1500, lambda: self._win.attributes("-topmost", False))
        self._tick()

    def _tick(self) -> None:
        if not self.alive:
            return
        snapshot = self._cb.snapshot()
        if not snapshot.armed:
            self.close()
            return
        self._countdown_var.set(format_duration(snapshot.remaining))
        self._win.after(500, self._tick)

    def _on_cancel(self) -> None:
        self._cb.on_cancel()
        self.close()

    def _on_postpone(self, minutes: int) -> None:
        self._cb.on_postpone(minutes)
        self.close()

    def close(self) -> None:
        if not self.alive:
            return
        self.alive = False
        self._win.destroy()

    def _centre(self, root: tk.Tk) -> None:
        self._win.update_idletasks()
        width = self._win.winfo_width()
        height = self._win.winfo_height()
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 3
        self._win.geometry(f"+{x}+{y}")
