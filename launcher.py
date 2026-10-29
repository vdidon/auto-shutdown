"""Entry point for PyInstaller.

A separate bootstrap script is needed: PyInstaller does not accept a module
launched with `-m`, and `src/auto_shutdown/__main__.py` uses relative imports
that require the package to be loaded as such.
"""

import sys

from auto_shutdown.app import main

if __name__ == "__main__":
    sys.exit(main())
