"""scripts/check_repo_rules.py: data_manager.py / plot_manager.py stay widget-free (#261)."""

import ast
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_repo_rules.py"
_spec = importlib.util.spec_from_file_location("check_repo_rules_layers", _SCRIPT)
rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rules)


def _modules(source):
    return [m for m, _line in rules._imported_modules(ast.parse(source))]


def test_widget_imports_are_found_also_inside_functions():
    source = (
        "import ipywidgets as w\n"
        "from IPython import display\n"
        "def f():\n"
        "    from IPython.display import HTML\n"
    )
    found = _modules(source)
    assert "ipywidgets" in found and "IPython.display" in found
    assert found.count("IPython.display") == 2


def test_get_ipython_is_not_a_widget_import():
    found = _modules("from IPython import get_ipython\n")
    assert not any(m.startswith("IPython.display") or m == "ipywidgets" for m in found)


def test_the_repo_passes_the_layer_rule():
    problems = []
    rules.check_python(problems)
    assert [p for p in problems if p[0] == "layer"] == []
