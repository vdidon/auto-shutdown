"""Reliable scheduling of a delayed sleep, hibernate, shutdown or lock.

Designed to avoid the common flaw of utilities of this kind: a task firing
again on resume, which puts the machine back to sleep a few seconds after
every wake-up.
"""

__version__ = "0.1.0"
