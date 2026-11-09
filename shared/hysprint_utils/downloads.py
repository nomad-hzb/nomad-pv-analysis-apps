"""Start a browser download from a widget callback, without a link to click.

The file goes to the browser as a Blob through one small script. A link with the whole
file as a base64 data URL makes a huge widget message, and the link itself is one more
click. Voila drops a bare display() inside on_click, so the script is shown through an
Output widget that stays in the displayed tree; ipywidgets.HTML would not run it.
"""

import base64
import json

from IPython.display import HTML, display


def download_script(content, filename, mime_type="application/octet-stream"):
    """<script> that downloads content (bytes or text, text as UTF-8) as filename.

    The file name and type are passed as JSON, so a quote in a name cannot break the script;
    the object URL is freed after a minute."""
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    encoded = base64.b64encode(data).decode("ascii")
    return f"""<script>
(function () {{
    var bytes = Uint8Array.from(atob('{encoded}'), function (c) {{ return c.charCodeAt(0); }});
    var url = URL.createObjectURL(new Blob([bytes], {{type: {json.dumps(mime_type)}}}));
    var link = document.createElement('a');
    link.href = url;
    link.download = {json.dumps(filename)};
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () {{ URL.revokeObjectURL(url); }}, 60000);
}})();
</script>"""


def start_download(output, content, filename, mime_type="application/octet-stream", note=""):
    """Replace what output shows with note (HTML, optional) and start the download.

    output: an ipywidgets.Output that is part of the displayed app. clear_output(wait=True)
    clears only when the new content arrives; a plain clear could land after it and wipe it."""
    with output:
        output.clear_output(wait=True)
        display(HTML(note + download_script(content, filename, mime_type)))
