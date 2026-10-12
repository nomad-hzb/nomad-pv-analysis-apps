"""ErrorHandler without a widget logs instead of writing to stdout; with one it prints into it."""

import io
import logging
from contextlib import redirect_stdout

from hysprint_utils.error_handler import ErrorHandler


def test_without_widget_logs_and_stays_off_stdout(caplog):
    buffer = io.StringIO()
    with redirect_stdout(buffer), caplog.at_level(logging.INFO):
        ErrorHandler.log_error("loading", ValueError("bad"))
        ErrorHandler.log_info("hello")
        ErrorHandler.log_success("done")
    assert buffer.getvalue() == ""
    assert "Error: loading: bad" in caplog.text
    assert "hello" in caplog.text and "done" in caplog.text


def test_with_widget_prints_into_it():
    class _Out:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ErrorHandler.log_info("shown", output_widget=_Out())
    assert "shown" in buffer.getvalue()
