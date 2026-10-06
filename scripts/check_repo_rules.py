"""Check the repo rules from CLAUDE.md that ruff cannot see. Run from anywhere:

    python scripts/check_repo_rules.py

Exits non-zero and lists every violation. Notebook-only folders that have not been ported
to the app layout yet are skipped, the same set ruff's extend-exclude skips.
"""

import ast
import json
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "apps"
PARKED = {"Electrochemical_analysis", "SEM_crystal_counter", "XPS-Automated"}

BOOTSTRAP_CELL = 'import runpy\n\n_ = runpy.run_path("../../bootstrap.py")'
OASIS_HOSTS = ("nomad-hzb-se", "helmholtz-berlin.de")

# Known violations, each tracked elsewhere. Remove an entry once it is fixed; the check
# fails if an entry no longer matches anything, so this list cannot go stale silently.
KNOWN_EXCEPTIONS = {
    # Installing it would apply its very new numpy/pandas/scipy pins to the shared
    # container; fix together with the pins (audit phase 5.5).
    ("pyproject", "apps/DesignOfExperiments/pyproject.toml"),
    # Link written into every generated workbook; where it should point is an open
    # decision (CLAUDE.md "Known gaps").
    ("url", "apps/Excel_creator/sheet_data_entry_guide.py:213"),
    # Deliberate: the SE Oasis is a fixed data source to download from, like the public
    # central server (CLAUDE.md "Known gaps").
    ("url", "apps/PeroDatabase_downloader/config.py:28"),
}


def app_dirs():
    return sorted(d for d in APPS.iterdir() if d.is_dir() and d.name not in PARKED)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def check_notebooks(problems):
    for app in app_dirs():
        for notebook in sorted(app.glob("*.ipynb")):
            cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
            code = [c for c in cells if c["cell_type"] == "code"]
            first = "".join(code[0]["source"]).strip() if code else ""
            if first != BOOTSTRAP_CELL:
                problems.append(
                    ("notebook", rel(notebook), "first code cell is not the bootstrap cell")
                )
            for cell in code[1:]:
                source = "".join(cell["source"])
                if "sys.path" in source:
                    problems.append(("sys.path", rel(notebook), "notebook changes sys.path"))
                if any(line.lstrip().startswith(("!pip", "%pip")) for line in source.splitlines()):
                    problems.append(("notebook", rel(notebook), "notebook installs packages"))


def _parents(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _in_import_error_fallback(node, parents) -> bool:
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            names = [node.type] + list(getattr(node.type, "elts", []))
            if any(getattr(n, "id", None) == "ImportError" for n in names):
                return True
    return False


def check_python(problems):
    for app in app_dirs():
        for source_file in sorted(app.glob("*.py")):
            text = source_file.read_text(encoding="utf-8")
            tree = ast.parse(text)
            parents = _parents(tree)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr in {"insert", "append"}
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "path"
                    and getattr(node.value.value, "id", None) == "sys"
                ):
                    problems.append(
                        ("sys.path", f"{rel(source_file)}:{node.lineno}", "sys.path change")
                    )
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith("http")
                    and any(host in node.value for host in OASIS_HOSTS)
                    and not _in_import_error_fallback(node, parents)
                ):
                    problems.append(
                        (
                            "url",
                            f"{rel(source_file)}:{node.lineno}",
                            "Oasis URL literal outside the ImportError fallback",
                        )
                    )
            if source_file.name.startswith("test_") or source_file.name == "conftest.py":
                problems.append(("tests", rel(source_file), "tests belong in tests/<App>/"))


def check_pyprojects(problems):
    for app in app_dirs():
        pyproject = app / "pyproject.toml"
        if not pyproject.exists():
            continue
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        deps = data.get("project", {}).get("dependencies", [])
        reasons = []
        if any("file://" in d for d in deps):
            reasons.append("file:// dependency")
        if any(d.split("[")[0].strip().lower().startswith(("pytest", "pytest-mock")) for d in deps):
            reasons.append("pytest in app dependencies")
        hatch = data.get("tool", {}).get("hatch", {})
        if hatch.get("build", {}).get("targets", {}).get("wheel", {}).get("packages") != ["."]:
            reasons.append('missing [tool.hatch.build.targets.wheel] packages = ["."]')
        if not hatch.get("metadata", {}).get("allow-direct-references"):
            reasons.append("missing [tool.hatch.metadata] allow-direct-references = true")
        if reasons:
            problems.append(("pyproject", rel(pyproject), "; ".join(reasons)))


def main() -> int:
    problems = []
    check_notebooks(problems)
    check_python(problems)
    check_pyprojects(problems)

    seen = {(kind, where) for kind, where, _ in problems}
    stale = sorted(KNOWN_EXCEPTIONS - seen)
    failures = [p for p in problems if (p[0], p[1]) not in KNOWN_EXCEPTIONS]

    for kind, where, what in failures:
        print(f"{where}: [{kind}] {what}")
    for kind, where in stale:
        print(f"{where}: [{kind}] listed in KNOWN_EXCEPTIONS but no longer fails; remove it")
    if failures or stale:
        print(f"\n{len(failures) + len(stale)} problem(s)")
        return 1
    print("Repo rules: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
