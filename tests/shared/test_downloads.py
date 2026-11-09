"""hysprint_utils.downloads: one Blob script per download, shown through an Output."""

import base64
import re

from hysprint_utils import downloads


def _payload(script):
    (encoded,) = re.findall(r"atob\('([A-Za-z0-9+/=]*)'\)", script)
    return base64.b64decode(encoded)


def test_script_carries_the_bytes_and_a_json_file_name():
    script = downloads.download_script(b"PK\x03\x04", "a\"b'.zip", "application/zip")
    assert _payload(script) == b"PK\x03\x04"
    assert 'link.download = "a\\"b\'.zip";' in script
    assert '{type: "application/zip"}' in script
    assert "onclick" not in script and "data:" not in script


def test_text_is_sent_as_utf8():
    assert _payload(downloads.download_script("ä,b\n", "x.csv", "text/csv")) == "ä,b\n".encode()


def test_start_download_clears_with_wait_and_shows_note_and_script(monkeypatch):
    shown, cleared = [], []

    class FakeOutput:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def clear_output(self, wait=False):
            cleared.append(wait)

    monkeypatch.setattr(downloads, "display", shown.append)
    downloads.start_download(FakeOutput(), b"x", "f.zip", "application/zip", note="<p>ready</p>")
    assert cleared == [True]
    (html,) = shown
    assert html.data.startswith("<p>ready</p><script>") and _payload(html.data) == b"x"
