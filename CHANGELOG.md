# Journal des modifications

Le projet suit le [versionnage sémantique](https://semver.org/lang/fr/) :
`MAJEUR.MINEUR.CORRECTIF`.

- **MAJEUR** — rupture de compatibilité : format de configuration incompatible,
  option de ligne de commande supprimée, comportement par défaut modifié d'une
  manière qui surprendrait un utilisateur existant.
- **MINEUR** — nouveauté rétrocompatible : action, déclencheur ou réglage
  supplémentaire.
- **CORRECTIF** — correction de bogue ou amélioration interne sans effet visible
  sur les réglages existants.

Le numéro vit dans `src/auto_shutdown/__init__.py` et dans `pyproject.toml` ; un
test interdit aux deux de diverger, et exige une entrée ici pour la version
courante.

---

## 0.1.0

Première version.

### Programmation

- Déclenchement après un délai exprimé en heures et minutes.
- Six actions : veille prolongée, veille, arrêt, redémarrage, fermeture de
  session, verrouillage de l'écran.
- Rappel avant l'échéance, avec annulation, report ou poursuite.
- Report de 5, 10, 15 ou 30 minutes, depuis le rappel comme depuis le menu de la
  zone de notification.

### Fiabilité

Le défaut visé est le redéclenchement d'une tâche au retour de veille, qui
renvoie la machine en veille quelques secondes après chaque réveil. Quatre
mécanismes s'y opposent :

- échéance fondée sur une horloge monotone, insensible aux changements d'heure ;
- désarmement de la tâche avant l'exécution de l'action ;
- annulation automatique à la reprise de veille, signalée par une notification ;
- annulation lorsque le décompte a été interrompu plus d'une minute, signe d'une
  machine suspendue — ce filet ne dépend d'aucune notification Windows.

S'y ajoute l'attente d'une période sans activité clavier ni souris avant toute
suspension, qui évite le réveil immédiat sur les machines dont la souris est
armée pour le réveil.

### Interface

- Icône de notification dont la couleur reflète l'état, menu contextuel,
  info-bulles.
- Fenêtre de configuration ouverte au lancement ; `--minimized` la supprime,
  pour le lancement automatique à l'ouverture de session.
- Journal horodaté de chaque armement, annulation, déclenchement et transition
  d'alimentation, ouvrable depuis le menu.

### Distribution

- Aucune dépendance d'exécution : `ctypes` et `tkinter` suffisent.
- Exécutable autonome d'environ 12 Mo produit par `build.ps1`.
- Icône générée en Python pur, sans Pillow.
