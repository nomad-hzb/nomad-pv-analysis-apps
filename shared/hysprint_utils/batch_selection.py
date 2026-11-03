import html
import logging

import ipywidgets as widgets
import requests
from natsort import natsorted

from hysprint_utils.api_calls import get_all_batches_wth_data, get_batch_ids
from hysprint_utils.plotting_utils import WidgetFactory

logger = logging.getLogger(__name__)

# The batch list and the filter button share one width, so the button label is never cut off.
PANEL_WIDTH = "400px"


def _top_level_batches(batch_ids):
    """Natural-sorted batch ids without the sub-batches whose parent is listed too
    (HZB_A_1 is hidden when HZB_A exists)."""
    batch_ids = list(batch_ids)
    all_batch_ids = set(batch_ids)
    return natsorted(b for b in batch_ids if "_".join(b.split("_")[:-1]) not in all_batch_ids)


def create_batch_selection(
    url,
    token,
    load_data_function,
    filter_label=None,
    filter_entry_type=None,
    filter_function=None,
):
    """Batch search field, batch list and Load Data button, as one VBox.

    children[0] is the search field and children[1] the SelectMultiple (apps rely on both).

    filter_label: the app's technique as users know it ("TRPL"). With it, a "Show TRPL only"
    button sits directly under the list, above Load Data, the same in every app. It narrows
    the list to the batches that have that measurement; clicked again it shows all batches.
    The search field always searches the list that is shown.
    filter_entry_type: the NOMAD entry type those batches must contain.
    filter_function: optional () -> batch ids, for an app that finds them another way.
    """
    # Get batch IDs. Without network or a valid token the app must still start, so its
    # demo mode stays reachable: the panel shows the error and an empty list instead.
    load_error = None
    try:
        batch_ids_list_tmp = list(get_batch_ids(url, token))
    except requests.RequestException as error:
        logger.warning("Could not load the batch list: %s", error)
        load_error = error
        batch_ids_list_tmp = []
    batch_ids_list = _top_level_batches(batch_ids_list_tmp)
    # The list the search works on: every batch, or only those the filter found.
    shown = {"ids": batch_ids_list, "filtered": False}

    # Create widgets using WidgetFactory for consistency
    batch_ids_selector = widgets.SelectMultiple(
        options=batch_ids_list,
        description="Batches",
        layout=widgets.Layout(width=PANEL_WIDTH, height="300px"),
    )

    search_field = widgets.Text(description="Search Batch")

    load_batch_button = WidgetFactory.create_button(description="Load Data", button_style="primary")

    def show_search_matches():
        term = search_field.value.strip().lower()
        batch_ids_selector.options = natsorted(d for d in shown["ids"] if term in d.lower())

    # Define search function
    def on_search_enter(change):
        show_search_matches()

    # Bind events
    search_field.observe(on_search_enter, names="value")
    load_batch_button.on_click(lambda b: load_data_function(batch_ids_selector))

    # Return the widget container. children[1] stays the SelectMultiple (apps rely on it).
    children = [search_field, batch_ids_selector]
    if filter_label:
        children.append(
            _filter_row(
                filter_label,
                filter_function
                or (lambda: get_all_batches_wth_data(url, token, filter_entry_type)),
                batch_ids_list,
                shown,
                show_search_matches,
            )
        )
    children.append(load_batch_button)
    if load_error is not None:
        children.append(
            widgets.HTML(
                "<p style='color:#b33'>Could not load the batch list from NOMAD "
                f"({html.escape(type(load_error).__name__)}). Check the connection or your "
                "token; demo data still works.</p>"
            )
        )
    return widgets.VBox(children)


def _filter_row(label, find_batches, all_batches, shown, show_search_matches):
    """The "Show <label> only" toggle and its one-line status, as wide as the batch list."""
    only_text = f"Show {label} only"
    button = WidgetFactory.create_button(
        description=only_text,
        button_style="info",
        tooltip=f"Ask NOMAD which batches have {label} data (can take a minute)",
    )
    button.layout = widgets.Layout(width=PANEL_WIDTH)
    status = widgets.HTML()

    def on_click(_b):
        if shown["filtered"]:
            shown.update(ids=all_batches, filtered=False)
            button.description = only_text
            status.value = ""
            show_search_matches()
            return
        button.disabled = True
        button.description = f"Searching NOMAD for {label} batches..."
        status.value = ""
        try:
            found = _top_level_batches(find_batches())
        except Exception as error:  # noqa: BLE001 - shown in the panel; the full list stays
            logger.warning("Could not filter the batches for %s: %s", label, error)
            status.value = (
                "<span style='color:#b33'>Could not ask NOMAD which batches have "
                f"{html.escape(label)} data ({html.escape(type(error).__name__)}).</span>"
            )
            button.description = only_text
        else:
            shown.update(ids=found, filtered=True)
            button.description = "Show all batches"
            status.value = html.escape(
                f"{len(found)} of {len(all_batches)} batches have {label} data."
            )
            show_search_matches()
        finally:
            button.disabled = False

    button.on_click(on_click)
    return widgets.VBox([button, status])
