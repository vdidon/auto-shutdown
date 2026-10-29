"""Point d'entrée pour PyInstaller.

Un script d'amorçage distinct est nécessaire : PyInstaller n'accepte pas de
module lancé par `-m`, et `src/auto_shutdown/__main__.py` utilise des imports
relatifs qui exigent que le paquet soit chargé comme tel.
"""

import sys

from auto_shutdown.app import main

if __name__ == "__main__":
    sys.exit(main())
