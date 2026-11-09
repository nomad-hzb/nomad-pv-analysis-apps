"""hysprint_utils.widget_cleanup: each build closes the widgets of the previous one."""

import warnings

import ipywidgets as widgets
import pytest

from hysprint_utils.widget_cleanup import UiRebuild, close_widgets, live_widgets


def test_a_new_build_closes_the_widgets_of_the_previous_one():
    rebuild = UiRebuild()
    clicks = []
    with rebuild.build():
        old = widgets.Button()
        old.on_click(lambda b: clicks.append("old"))
        old_id = old.model_id
    assert old_id in rebuild.widget_ids and old_id in live_widgets()

    with rebuild.build():
        new = widgets.Button()
    assert old_id not in live_widgets()
    assert new.model_id in live_widgets() and new.model_id in rebuild.widget_ids
    assert old_id not in rebuild.widget_ids  # (a Button brings its Layout and style too)


def test_widgets_from_before_the_build_are_left_alone():
    outside = widgets.Label("singleton")
    rebuild = UiRebuild()
    for _ in range(2):
        with rebuild.build():
            widgets.Button()
    assert outside.model_id in live_widgets()
    outside.close()


def test_a_failed_build_is_still_cleaned_up_next_time():
    rebuild = UiRebuild()
    with pytest.raises(RuntimeError), rebuild.build():
        half = widgets.Button()
        raise RuntimeError("build failed")
    half_id = half.model_id
    with rebuild.build():
        pass
    assert half_id not in live_widgets()


def test_close_widgets_skips_missing_ids_and_survives_a_failing_close(monkeypatch, caplog):
    broken = widgets.Button()

    def fail():
        raise RuntimeError("cannot close")

    monkeypatch.setattr(broken, "close", fail)
    fine = widgets.Button()
    fine_id = fine.model_id
    close_widgets({"not-a-widget", broken.model_id, fine_id})
    assert fine_id not in live_widgets()
    assert "Could not close stale widget" in caplog.text


def test_the_deprecated_registry_is_not_used():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        rebuild = UiRebuild()
        with rebuild.build():
            widgets.Button()
        with rebuild.build():
            pass
