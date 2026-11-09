"""Widget lifecycle of the XRD GUI panels."""

from gui_components import SampleGridPanel

from hysprint_utils.widget_cleanup import live_widgets


def test_refresh_closes_the_rows_it_replaces(sample_data_dict):
    """Replacing children only hides the old rows; each refresh would keep them all alive."""
    panel = SampleGridPanel()
    panel.refresh(sample_data_dict)
    first = list(panel._container.children)
    assert first
    panel.refresh(sample_data_dict)
    assert all(widget.comm is None for widget in first)  # closed
    assert all(widget.comm is not None for widget in panel._container.children)
    assert panel._row_widget_ids <= set(live_widgets())


def test_refresh_with_no_data_closes_the_old_rows(sample_data_dict):
    panel = SampleGridPanel()
    panel.refresh(sample_data_dict)
    first = list(panel._container.children)
    panel.refresh({})
    assert panel._container.children == ()
    assert all(widget.comm is None for widget in first)
