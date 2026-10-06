"""Install what one tests/<suite> folder needs, the way bootstrap.py would on the Oasis:
shared/ plus the dependencies the app declares in its own pyproject.toml, plus the test
tools. Keeping CI on the declared lists means a missing dependency fails here instead of
on a fresh container.

    python scripts/ci_install_test_deps.py <suite>
"""

import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
TEST_TOOLS = ["pytest", "pytest-mock"]


def requirements(suite: str) -> list[str]:
    pyproject = ROOT / "apps" / suite / "pyproject.toml"
    if not pyproject.exists():  # tests/shared and other non-app folders
        return []
    deps = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"].get("dependencies", [])
    return [d for d in deps if not d.strip().lower().startswith("hysprint-utils")]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    command = [sys.executable, "-m", "pip", "install", "-e", str(ROOT / "shared")]
    command += TEST_TOOLS + requirements(sys.argv[1])
    print(" ".join(command), flush=True)
    return subprocess.call(command)


if __name__ == "__main__":
    sys.exit(main())
