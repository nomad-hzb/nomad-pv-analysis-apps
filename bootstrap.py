"""Bootstrap run at the top of every app notebook, before any app import.

Installs hysprint_utils from shared/ and, only if a deployment opts in,
applies a local outbound-proxy configuration before that install runs (pip
reaches PyPI for build dependencies, so the proxy has to be in place first).

Proxy support is opt-in and off by default: the HZB Oasis needs none of
this, and this file must never hardcode a deployment-specific proxy value.
A deployment that needs one creates oasis_local_config.py next to this file
(gitignored, same pattern as secrets.py) defining HTTP_PROXY/HTTPS_PROXY
and optionally NO_PROXY - or sets those variables at the container level,
which this file leaves untouched.

Notebooks invoke this via a fixed 2-line cell 0 (cwd is always the
notebook's own directory under Voila, regardless of the upload session
hash, so the relative path here is invariant):

    import runpy
    runpy.run_path("../../bootstrap.py")
"""

import importlib
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent


def _apply_local_proxy_config() -> None:
    if os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY"):
        return

    config_path = REPO_ROOT / "oasis_local_config.py"
    if not config_path.exists():
        return

    namespace: dict = {}
    exec(config_path.read_text(encoding="utf-8"), namespace)  # noqa: S102

    http_proxy = namespace.get("HTTP_PROXY")
    https_proxy = namespace.get("HTTPS_PROXY")
    if not (http_proxy or https_proxy):
        return

    if http_proxy:
        os.environ["HTTP_PROXY"] = http_proxy
    if https_proxy:
        os.environ["HTTPS_PROXY"] = https_proxy

    no_proxy = namespace.get("NO_PROXY")
    if no_proxy is None:
        # The Oasis this notebook talks to is a local/in-house call, not an
        # external one - route it (and localhost) around the proxy unless
        # the deployment says otherwise.
        oasis_url = os.environ.get("HYSPRINT_URL_BASE", "https://nomad-hzb-se.de")
        oasis_host = urlparse(oasis_url).hostname or ""
        no_proxy = ",".join(filter(None, ["localhost", "127.0.0.1", oasis_host]))
    os.environ["NO_PROXY"] = no_proxy

    logger.info("Applied local proxy configuration from %s", config_path)


def _install_shared() -> None:
    shared = REPO_ROOT / "shared"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", str(shared)],
        check=True,
    )
    # A fresh kernel already ran site.py before this install happened, so it
    # won't pick up the newly installed package on its own until restarted.
    # Adding shared/ to sys.path directly makes THIS kernel see hysprint_utils
    # immediately, without needing a second run. Confirmed necessary in
    # App_dashboard (issue with Voila needing "to be run twice"); a deliberate
    # exception to CLAUDE.md rule 8, not a violation to clean up.
    shared_str = str(shared)
    if shared_str not in sys.path:
        sys.path.insert(0, shared_str)


_apply_local_proxy_config()
_install_shared()
importlib.invalidate_caches()
