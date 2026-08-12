"""pytest bootstrap.

A conftest at the package root puts this directory on ``sys.path`` (pytest's
default prepend import mode), so ``from server import ...`` resolves when
running pytest from anywhere.
"""
