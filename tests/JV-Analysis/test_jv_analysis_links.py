"""Links to other measurements: derived from the configured API URL, NOMAD text escaped."""

from utils import measurement_link_html

HZB_API = "https://nomad-hzb-se.helmholtz-berlin.de/nomad-oasis/api/v1"


def test_link_follows_the_api_mount_point():
    link = measurement_link_html(HZB_API, "abc123", "HySprint_EQEmeasurement")
    gui = "https://nomad-hzb-se.helmholtz-berlin.de/nomad-oasis/gui"
    assert f'href="{gui}/entry/id/abc123/data/data"' in link
    assert ">EQEmeasurement</a>" in link


def test_link_on_an_oasis_mounted_elsewhere():
    link = measurement_link_html("https://oasis.example.org/api/v1", "e1", "HySprint_XRD_XY")
    assert 'href="https://oasis.example.org/gui/entry/id/e1/data/data"' in link
    assert "/nomad-oasis/" not in link


def test_sem_link_opens_the_image_preview():
    link = measurement_link_html(HZB_API, "e1", "HySprint_SEM")
    assert "/entry/id/e1/data/data/images:0/image_preview/preview" in link


def test_nomad_text_is_escaped():
    link = measurement_link_html(HZB_API, 'x"><script>', "HySprint_<img src=x onerror=alert(1)>")
    assert "<script>" not in link
    assert "<img" not in link
    assert "&lt;img src=x onerror=alert(1)&gt;" in link
