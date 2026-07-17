"""Monorepo-wide pytest configuration.

The repo root has its own ``secrets.py`` (used by
``hysprint_utils.access_token.get_token()`` for the local-login fallback).
When pytest is invoked from the repo root, Python's default sys.path[0]
(the empty string, meaning "current directory") lets that file shadow the
stdlib ``secrets`` module for every test. Recent numpy/plotly versions
import ``secrets.randbits``/``secrets.token_hex`` internally, so without this
guard almost any test that touches pandas, numpy, or plotly fails with
``ImportError: cannot import name 'randbits'/'token_hex' from 'secrets'``.

Strip the repo-root entry before any test module (and therefore any
app's data_manager/plot_manager) gets imported, so the real stdlib
``secrets`` resolves normally. This never touches secrets.py itself or its
walk-up discovery in get_token(), which is Path-based, not sys.path-based.
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)

for _entry in ("", _REPO_ROOT):
    while _entry in sys.path:
        sys.path.remove(_entry)
