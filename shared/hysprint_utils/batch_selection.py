import html
import logging

import ipywidgets as widgets
import requests
from natsort import natsorted

from hysprint_utils.api_calls import get_batch_ids
from hysprint_utils.plotting_utils import WidgetFactory

logger = logging.getLogger(__name__)


def create_batch_selection(url, token, load_data_function):
    # Get batch IDs. Without network or a valid token the app must still start, so its
    # demo mode stays reachable: the panel shows the error and an empty list instead.
    load_error = None
    try:
        batch_ids_list_tmp = list(get_batch_ids(url, token))
    except requests.RequestException as error:
        logger.warning("Could not load the batch list: %s", error)
        load_error = error
        batch_ids_list_tmp = []
    all_batch_ids = set(batch_ids_list_tmp)
    batch_ids_list = [
        b for b in batch_ids_list_tmp if "_".join(b.split("_")[:-1]) not in all_batch_ids
    ]

    batch_ids_list = natsorted(batch_ids_list)

    # Create widgets using WidgetFactory for consistency
    batch_ids_selector = widgets.SelectMultiple(
        options=batch_ids_list,
        description="Batches",
        layout=widgets.Layout(width="400px", height="300px"),
    )

    search_field = widgets.Text(description="Search Batch")

    load_batch_button = WidgetFactory.create_button(description="Load Data", button_style="primary")

    # Define search function
    def on_search_enter(change):
        filtered = natsorted(
            [d for d in batch_ids_list if search_field.value.strip().lower() in d.lower()]
        )
        batch_ids_selector.options = filtered

    # Bind events
    search_field.observe(on_search_enter, names="value")
    load_batch_button.on_click(lambda b: load_data_function(batch_ids_selector))

    # Return the widget container. children[1] stays the SelectMultiple (apps rely on it).
    children = [search_field, batch_ids_selector, load_batch_button]
    if load_error is not None:
        children.append(
            widgets.HTML(
                "<p style='color:#b33'>Could not load the batch list from NOMAD "
                f"({html.escape(type(load_error).__name__)}). Check the connection or your "
                "token; demo data still works.</p>"
            )
        )
    return widgets.VBox(children)
