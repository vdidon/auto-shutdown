"""French interface texts. Keys and placeholders mirror `locales.en`."""

from typing import Final

MESSAGES: Final[dict[str, str]] = {
    # Actions, as listed in the configuration window.
    "action.HIBERNATE": "Mettre en veille prolongée",
    "action.SLEEP": "Mettre en veille",
    "action.SHUTDOWN": "Arrêter",
    "action.RESTART": "Redémarrer",
    "action.LOGOFF": "Fermer la session",
    "action.LOCK": "Verrouiller l'écran",
    "action.unknown": "L'action programmée",
    # Task state, shared by the configuration window, tray tooltip and menu.
    "status.armed": "{action} dans {remaining}",
    "status.idle": "Aucune tâche programmée",
    # Configuration window.
    "config.action": "Action à exécuter",
    "config.delay": "À partir de maintenant, dans",
    "config.hours": "heure(s)",
    "config.minutes": "minute(s)",
    "config.remind": "Me prévenir",
    "config.remind_before": "minute(s) avant",
    "config.close": "Fermer",
    "config.cancel_task": "Annuler la tâche",
    "config.start": "Démarrer",
    "config.version": "version {version}",
    "config.error.not_integer": "Le délai doit être un nombre entier.",
    "config.error.too_short": "Le délai doit valoir au moins une minute.",
    "config.error.too_long": "Le délai ne peut pas dépasser sept jours.",
    # Reminder window.
    "reminder.title": "Auto Shutdown — rappel",
    "reminder.heading": "{action} dans",
    "reminder.postpone": "Reporter de",
    "reminder.postpone_choice": "{minutes} min",
    "reminder.cancel": "Annuler",
    "reminder.dismiss": "Laisser faire",
    # Tray context menu.
    "menu.configure": "Configurer et armer…",
    "menu.postpone": "Reporter de",
    "menu.postpone_choice": "{minutes} minutes",
    "menu.cancel": "Annuler la tâche",
    "menu.open_log": "Ouvrir le journal",
    "menu.quit": "Quitter",
    # Tray notifications.
    "notify.armed.title": "Tâche programmée",
    "notify.armed.body": "{action} dans {remaining}.",
    "notify.postponed.title": "Tâche reportée",
    "notify.postponed.body": "Nouvelle échéance dans {minutes} minutes.",
    "notify.reminder.title": "Rappel",
    "notify.reminder.body": "{action} dans {remaining}.",
    "notify.cancelled.title": "Tâche annulée",
    "notify.cancelled.resume": (
        "La machine est sortie de veille : la tâche programmée a été annulée "
        "pour éviter un nouveau cycle de veille."
    ),
    "notify.cancelled.stall": (
        "Le décompte a été interrompu, signe que la machine a été suspendue. "
        "La tâche a été annulée par sécurité."
    ),
}
