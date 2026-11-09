# api_calls.py
# methods to access the nomad api

import getpass
import logging
import re
import time
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from hysprint_utils.config import ENTRY_TYPES

logger = logging.getLogger(__name__)

# (connect, read) seconds for every request. Archive queries of a few thousand entries are
# slow, so the read timeout is generous; it only exists so a dead server cannot hang an app.
REQUEST_TIMEOUT = (10, 300)
DEFAULT_PAGE_SIZE = 10000

# Answers of an overloaded or restarting Oasis proxy that are worth one more try.
TRANSIENT_STATUSES = (502, 503, 504)


def _make_session(retry_transient):
    """A requests.Session: one kept-alive connection per host instead of a new TLS handshake
    per request (query_all pages, one /users lookup per author, upload polls).

    With retry_transient, a 502/503/504 or a failed connect is tried again up to 3 times
    (waits of about 1, 2 and 4 s), for GET and POST. A read timeout is not retried: the read
    timeout is 300 s, so retrying it would hold an app for many minutes. After the last try
    the response is returned as it is, so raise_for_status reports it as before."""
    session = requests.Session()
    if retry_transient:
        retry = Retry(
            total=3,
            connect=3,
            read=0,
            status=3,
            backoff_factor=1.0,
            status_forcelist=TRANSIENT_STATUSES,
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
            respect_retry_after_header=False,  # keeps the wait bounded
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    return session


# Reads, queries (POST to entries/query) and logins: safe to send again.
SESSION = _make_session(retry_transient=True)
# Uploads, processing requests and edits are never retried, so nothing is sent twice.
WRITE_SESSION = _make_session(retry_transient=False)


class EntryLookupError(LookupError, AssertionError):
    """NOMAD did not return the entry (or entries) a lookup needs: none, or several where
    exactly one is expected. These lookups used assert before, which python -O skips; the
    AssertionError base keeps every existing `except AssertionError` handler working."""


def _exactly_one(data, what):
    """The only item of data, or EntryLookupError naming what was looked up."""
    if len(data) != 1:
        found = "no entry" if not data else f"{len(data)} entries"
        raise EntryLookupError(f"NOMAD returned {found} for {what}, expected exactly one")
    return data[0]


# Safety stop for the page loop (a server that keeps returning a next page forever).
MAX_PAGES = 1000


def query_all(url, token, endpoint, query, timeout=REQUEST_TIMEOUT):
    """POST a NOMAD query and return the "data" of every page, in order.

    Follows pagination.next_page_after_value, so a result larger than the page size is
    returned complete instead of silently cut off. Raises requests.HTTPError on a failed
    page. The caller's query is not modified. A query without a page size gets
    DEFAULT_PAGE_SIZE.
    """
    query = {**query, "pagination": {"page_size": DEFAULT_PAGE_SIZE, **query.get("pagination", {})}}
    headers = {"Authorization": f"Bearer {token}"}
    data = []
    seen_cursors = set()
    for _ in range(MAX_PAGES):
        response = SESSION.post(f"{url}/{endpoint}", headers=headers, json=query, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        data.extend(payload["data"])
        cursor = (payload.get("pagination") or {}).get("next_page_after_value")
        if not cursor or cursor in seen_cursors:
            return data
        seen_cursors.add(cursor)
        query = {**query, "pagination": {**query["pagination"], "page_after_value": cursor}}
    logger.warning(
        "query to %s stopped after %d pages; the result may be incomplete", endpoint, MAX_PAGES
    )
    return data


# Old private name, kept so code written against it keeps working.
_query_all = query_all


def edit_entry(url, token, entry_id, changes):
    """Patch fields on an existing entry's archive via NOMAD's own ELN-edit endpoint.

    changes: list of {"path": <dotted path into the archive, e.g.
    "data.results.0.T80">, "new_value": <value>, "action": "upsert"}
    ("action" defaults to "upsert" server-side if omitted).

    Raises requests.HTTPError on failure (400/403/404/422) - the response body
    carries NOMAD's own detail/validation-error text, which callers should
    surface as-is rather than replacing with a generic message.
    """
    response = WRITE_SESSION.post(
        f"{url}/entries/{entry_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"changes": changes},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# retreive information about all uploads of current user
def get_all_uploads(url, token, number_of_uploads=20):
    response = SESSION.get(
        f"{url}/uploads",
        headers={"Authorization": f"Bearer {token}"},
        params=dict(page_size=number_of_uploads, order_by="upload_create_time", order="desc"),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["data"]


_ARCHIVE_REFERENCE_RE = re.compile(r"archive/([^#]+)#")


def entry_id_from_reference(reference):
    """The entry_id of an archive reference such as
    '../uploads/{upload_id}/archive/{entry_id}#/data', or None for anything else (the format
    of HySprint_Sample.substrate, see smart_databaser's own copy of this)."""
    if not isinstance(reference, str):
        return None
    match = _ARCHIVE_REFERENCE_RE.search(reference)
    return match.group(1) if match else None


def get_samples_with_substrates(url, token, upload_id, sample_type=ENTRY_TYPES["sample"]):
    """[{"sample": <sample data>, "substrate": <substrate data, or {}>}] for every sample
    entry of the upload, in the shape process_specs' Experiment Info paths read
    (["substrate", "substrate"], ["sample", "number_of_junctions"], ...).

    Two queries whatever the number of samples: the samples, then all the substrate
    entries they reference (which may sit in another upload). A substrate that cannot be
    found gives {}."""
    query = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"upload_id": upload_id, "entry_type": sample_type},
        "pagination": {"page_size": 1000},
    }
    samples = [
        (entry.get("archive") or {}).get("data") or {}
        for entry in query_all(url, token, "entries/archive/query", query)
    ]
    substrate_ids = {entry_id_from_reference(s.get("substrate")) for s in samples} - {None}
    substrates = {}
    if substrate_ids:
        query = {
            "required": {"data": "*"},
            "owner": "visible",
            "query": {"entry_id:any": sorted(substrate_ids)},
            "pagination": {"page_size": 1000},
        }
        for entry in query_all(url, token, "entries/archive/query", query):
            substrates[entry.get("entry_id")] = (entry.get("archive") or {}).get("data") or {}
    return [
        {"sample": s, "substrate": substrates.get(entry_id_from_reference(s.get("substrate")), {})}
        for s in samples
    ]


# Uploads per batch query in get_all_batches_wth_data: one upload_id:any list with every
# upload of a large technique (JV) makes a single very large request.
BATCH_LOOKUP_UPLOAD_CHUNK = 200


def get_all_batches_wth_data(url, token, entry_type):
    """Lab ids of the batches in every upload that has an entry of entry_type.

    Asks only for what it needs, so the answers stay small even for JV, the technique with
    the most entries: the upload_id of each measurement (metadata endpoint; the archive
    endpoint answered with an HTTP error for JV and MPPT), then the lab_id of the batches in
    those uploads, a chunk of uploads at a time. A batch entry without lab_id is skipped."""
    query = {
        "owner": "visible",
        "query": {"entry_type": entry_type},
        "required": {"include": ["upload_id"]},
        "pagination": {"page_size": 10000},
    }
    entries = query_all(url, token, "entries/query", query)
    upload_ids = sorted({e["upload_id"] for e in entries if "upload_id" in e})
    batch_ids = set()
    for start in range(0, len(upload_ids), BATCH_LOOKUP_UPLOAD_CHUNK):
        query = {
            "required": {"data": {"lab_id": "*"}},
            "owner": "visible",
            "query": {
                "entry_type": ENTRY_TYPES["batch"],
                "upload_id:any": upload_ids[start : start + BATCH_LOOKUP_UPLOAD_CHUNK],
            },
            "pagination": {"page_size": 1000},
        }
        for batch in query_all(url, token, "entries/archive/query", query):
            lab_id = ((batch.get("archive") or {}).get("data") or {}).get("lab_id")
            if lab_id:
                batch_ids.add(lab_id)
    return list(batch_ids)


def get_template(url, token, upload_name, method):
    query = {
        "required": {
            "data": "*",
        },
        "owner": "visible",
        "query": {"upload_name": upload_name, "entry_type": method},
        "pagination": {"page_size": 100},
    }
    data = query_all(url, token, "entries/archive/query", query)
    return data


def _error_detail(response):
    """NOMAD's own reason for a refused request ("detail"), else the start of the body."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return str(detail) if detail else (response.text or "")[:200]


def password_login(url, username, password, timeout=REQUEST_TIMEOUT):
    """A NOMAD access token for username and password: the one login every module uses.

    POSTs to {url}/auth/token as form data (never in the URL, which would leak the password
    into logs). Raises requests.HTTPError with NOMAD's reason (e.g. "Invalid credentials")
    and the response attached when the login is refused, ValueError when the answer holds
    no token."""
    response = SESSION.post(
        f"{url}/auth/token",
        data={"username": username, "password": password},
        timeout=timeout,
    )
    if not response.ok:
        raise requests.HTTPError(
            f"NOMAD login failed ({response.status_code}): {_error_detail(response)}",
            response=response,
        )
    token = (response.json() or {}).get("access_token")
    if not token:
        raise ValueError("Access token not found in response.")
    return token


def prompt_login(url, name=None, timeout=REQUEST_TIMEOUT):
    """Ask for the username (unless name is given) and the password, then password_login."""
    user = name if name is not None else input("Username: ")
    return password_login(url, user, getpass.getpass("Password: "), timeout=timeout)


def get_token(url, name=None):
    """Interactive login (prompts for the password). Kept for old notebooks; apps get their
    token from access_token.get_token, which tries the environment and token file first."""
    return prompt_login(url, name)


def get_batch_ids(url, token, batch_type=ENTRY_TYPES["batch"]):
    query = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"entry_type": batch_type},
        "pagination": {"page_size": 10000},
    }
    data = query_all(url, token, "entries/archive/query", query)
    return [d["archive"]["data"]["lab_id"] for d in data if "lab_id" in d["archive"]["data"]]


def _resolve_user_names(url, token, user_ids):
    """Resolve raw NOMAD user_ids to display names via the /users endpoint - the same
    one /users/me (see auth_manager.APIClient.get_user_verification_url) uses for the
    current user, just parameterized by id instead of "me". Best-effort: an id that
    can't be resolved is simply left out of the returned dict rather than raising, so
    one bad/renamed id doesn't break the whole batch list.
    """
    headers = {"Authorization": f"Bearer {token}"}
    names = {}
    for user_id in user_ids:
        try:
            response = SESSION.get(
                f"{url}/users",
                headers=headers,
                params={"user_id": user_id},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            matches = response.json().get("data") or []
            if matches:
                user = matches[0]
                name = user.get("name") or user.get("username")
                if name:
                    names[user_id] = name
        except requests.RequestException:
            continue
    return names


def get_batch_ids_with_authors(url, token, batch_type=ENTRY_TYPES["batch"]):
    """Like get_batch_ids, but also resolves each batch's author display name.

    Requesting 'metadata' (not just 'data') is what makes author info available at
    all. Confirmed live against this HZB oasis: metadata.authors is a list of user
    objects with a usable 'name' field - that's the primary source used below.
    metadata.main_author is kept only as a fallback for entries with no resolved
    'authors' entry, since its own shape varies (a nested user object on some
    deployments, a bare user_id string needing a /users lookup on others).
    """
    query = {
        "required": {"data": "*", "metadata": "*"},
        "owner": "visible",
        "query": {"entry_type": batch_type},
        "pagination": {"page_size": 10000},
    }
    data = query_all(url, token, "entries/archive/query", query)

    records = []
    unresolved_user_ids = set()
    for d in data:
        archive = d["archive"]
        lab_id = (archive.get("data") or {}).get("lab_id")
        if not lab_id:
            continue

        metadata = archive.get("metadata") or {}
        author_name = None
        user_id = None

        authors = metadata.get("authors") or []
        first_author = authors[0] if authors else None
        if isinstance(first_author, dict):
            author_name = first_author.get("name") or first_author.get("username")
        elif isinstance(first_author, str) and first_author.strip():
            author_name = first_author.strip()

        if not author_name:
            main_author = metadata.get("main_author")
            if isinstance(main_author, dict):
                author_name = main_author.get("name") or main_author.get("username")
                user_id = main_author.get("user_id")
            elif isinstance(main_author, str) and main_author.strip():
                user_id = main_author.strip()

        if not author_name and user_id:
            unresolved_user_ids.add(user_id)
        records.append({"lab_id": lab_id, "author_name": author_name, "user_id": user_id})

    resolved_names = (
        _resolve_user_names(url, token, unresolved_user_ids) if unresolved_user_ids else {}
    )

    results = []
    for record in records:
        author_name = record["author_name"]
        if not author_name and record["user_id"]:
            author_name = resolved_names.get(record["user_id"])
        results.append({"lab_id": record["lab_id"], "author_name": author_name or "Unknown"})
    return results


def get_ids_in_batch(url, token, batch_ids, batch_type=ENTRY_TYPES["batch"]):
    query = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": batch_ids, "entry_type": batch_type},
        "pagination": {"page_size": 100},
    }
    data = query_all(url, token, "entries/archive/query", query)
    if len(data) != len(batch_ids):
        logger.warning("asked for %d batches, NOMAD returned %d", len(batch_ids), len(data))
    sample_ids = []
    for d in data:
        dd = d["archive"]["data"]
        if "entities" in dd:
            sample_ids.extend([s["lab_id"] for s in dd["entities"]])
    return sample_ids


def get_entry_data(url, token, entry_id):

    row = {"entry_id": entry_id}
    query = {
        "required": {
            "metadata": "*",
            "data": "*",
        },
        "owner": "visible",
        "query": row,
        "pagination": {"page_size": 10000},
    }
    data = query_all(url, token, "entries/archive/query", query)
    return _exactly_one(data, f"entry_id {entry_id!r}")["archive"]["data"]


def get_sample_description(url, token, sample_ids):
    query = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    entries = query_all(url, token, "entries/query", query)
    res = {}
    for entry in entries:
        data = entry["data"]
        if "description" in data and data["description"] and data["description"].strip():
            res.update({data["lab_id"]: data["description"]})
    return res


def get_entryid(url, token, sample_id):  # give it a batch id
    # get al entries related to this batch id
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids": sample_id},
        "pagination": {"page_size": 100},
    }
    data = query_all(url, token, "entries/query", query)
    return _exactly_one(data, f"lab_id {sample_id!r}")["entry_id"]


def get_nomad_ids_of_entry(url, token, sample_id):  # give it a batch id
    # get al entries related to this batch id
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids": sample_id},
        "pagination": {"page_size": 100},
    }
    entry = _exactly_one(query_all(url, token, "entries/query", query), f"lab_id {sample_id!r}")
    return entry["entry_id"], entry["upload_id"]


def get_upload_ids_for_samples(url, token, sample_ids):
    """{sample lab_id: upload_id} for all samples in one query (paginated, with a timeout).

    Samples without an entry are left out. Use this instead of one get_nomad_ids_of_entry call
    per sample."""
    sample_ids = list(sample_ids)
    if not sample_ids:
        return {}
    query = {
        "required": {"include": ["entry_id", "upload_id", "results.eln.lab_ids"]},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": DEFAULT_PAGE_SIZE},
    }
    wanted = set(sample_ids)
    found = {}
    for entry in query_all(url, token, "entries/query", query):
        upload_id = entry.get("upload_id")
        lab_ids = ((entry.get("results") or {}).get("eln") or {}).get("lab_ids") or []
        for lab_id in lab_ids:
            if lab_id in wanted and upload_id:
                found.setdefault(lab_id, upload_id)
    return found


def upload_raw_file_and_wait(
    url,
    token,
    upload_id,
    filename,
    content,
    mime_type,
    poll_interval=2.0,
    max_wait=900.0,
    on_poll=None,
):
    """PUT one file (bytes) into an upload's raw folder and wait until NOMAD has processed it.

    Raises requests.HTTPError when the PUT fails, RuntimeError when NOMAD reports the
    processing as failed (with its message) and TimeoutError after max_wait seconds. The PUT
    already starts processing on this NOMAD version; the one explicit process request after it
    is tolerated to fail, the poll decides the outcome. on_poll(waited, max_wait), if given,
    is called after each poll (for a progress bar)."""
    headers = {"Authorization": f"Bearer {token}"}
    put_response = WRITE_SESSION.put(
        f"{url}/uploads/{upload_id}/raw/",
        data={"wait_for_processing": False},
        headers=headers,
        files={"file": (filename, content, mime_type)},
        timeout=REQUEST_TIMEOUT,
    )
    put_response.raise_for_status()
    WRITE_SESSION.post(
        f"{url}/uploads/{upload_id}/action/process", headers=headers, timeout=REQUEST_TIMEOUT
    )

    waited = 0.0
    while waited < max_wait:
        time.sleep(poll_interval)
        waited += poll_interval
        response = SESSION.get(
            f"{url}/uploads/{upload_id}", headers=headers, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        upload = response.json()["data"]
        if on_poll is not None:
            on_poll(waited, max_wait)
        if not upload["process_running"]:
            if upload.get("process_status") == "FAILURE":
                detail = upload.get("last_status_message") or "no message from NOMAD"
                raise RuntimeError(f"NOMAD could not process {filename}: {detail}")
            return
    raise TimeoutError(f"processing of {filename} did not finish within {int(max_wait)} s")


def download_raw_file(url, token, upload_id, path):
    """Bytes of one raw file of an upload. `path` is relative to the upload's raw folder, as
    NOMAD stores it in file references such as an SEM entry's data.detector_data. Raises
    requests.HTTPError when the file cannot be fetched."""
    response = SESSION.get(
        f"{url}/uploads/{upload_id}/raw/{quote(path, safe='/')}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.content


def get_sample_entry_links(url, token, sample_ids):
    """
    Batch query: returns {lab_id: full_gui_url} for all sample_ids in one API call.
    GUI URL pattern: {base}/gui/user/uploads/upload/id/{upload_id}/entry/id/{entry_id}
    """
    base_url = url.split("/api/")[0]  # e.g. https://nomad-hzb-se.helmholtz-berlin.de/nomad-oasis

    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    data = query_all(url, token, "entries/query", query)

    result = {}
    for entry in data:
        entry_id = entry.get("entry_id")
        upload_id = entry.get("upload_id")
        lab_ids = (entry.get("results") or {}).get("eln", {}).get("lab_ids", [])
        if not entry_id or not upload_id:
            continue
        gui_url = f"{base_url}/gui/user/uploads/upload/id/{upload_id}/entry/id/{entry_id}"
        for lab_id in lab_ids:
            if lab_id in sample_ids:
                result[lab_id] = gui_url

    logger.debug(
        "get_sample_entry_links: resolved %d/%d sample links", len(result), len(sample_ids)
    )
    return result


def get_entry_meta_data(url, token, entry_id):

    row = {"entry_id": entry_id}
    query = {
        "required": {
            "metadata": "*",
        },
        "owner": "visible",
        "query": row,
        "pagination": {"page_size": 100},
    }
    data = query_all(url, token, "entries/query", query)
    return _exactly_one(data, f"entry_id {entry_id!r}")


def get_information(url, token, entry_id, path):
    mdata = get_entry_meta_data(url, token, entry_id)
    res = []
    for ref in mdata.get("entry_references"):
        if path != ref.get("source_path"):
            continue
        res.append(get_entry_data(url, token, ref.get("target_entry_id")))

    return res


def get_setup(url, token, entry_id):
    data = get_information(url, token, entry_id, "data.setup")
    return _exactly_one(data, f"the setup of entry {entry_id!r}")


def get_environment(url, token, entry_id):
    data = get_information(url, token, entry_id, "data.environment")
    return _exactly_one(data, f"the environment of entry {entry_id!r}")


def get_samples(url, token, entry_id):
    data = get_information(url, token, entry_id, "data.samples.reference")
    if not data:
        raise EntryLookupError(f"NOMAD returned no samples for entry {entry_id!r}")
    return data


def get_specific_data_of_sample(url, token, sample_id, entry_type, with_meta=False):
    # collect the results of the sample, in this case it are all the annealing temperatures
    entry_id = get_entryid(url, token, sample_id)

    query = {
        "required": {
            "metadata": "*",
            "data": "*",
        },
        "owner": "visible",
        "query": {"entry_references.target_entry_id": entry_id},
        "pagination": {"page_size": 100},
    }
    linked_data = query_all(url, token, "entries/archive/query", query)
    res = []
    for ldata in linked_data:
        if (
            "entry_type" not in ldata["archive"]["metadata"]
            or entry_type not in ldata["archive"]["metadata"]["entry_type"]
        ):
            continue
        if with_meta:
            res.append((ldata["archive"]["data"], ldata["archive"]["metadata"]))
        else:
            res.append(ldata["archive"]["data"])
    return res


def _index_linked_data_by_sample(linked_data):
    """Index (archive_data, archive_metadata) pairs by every sample each entry references.

    An entry's `samples` field can list more than one sample - e.g. several
    substrates annealed together in one oven run, or a process step logged
    once for a whole batch - and each of those samples genuinely underwent
    that process/measurement. Indexing by only `samples[0]` (the previous
    behavior here) silently dropped the entry for every other referenced
    sample, indistinguishable downstream from that sample never having been
    processed that way at all.
    """
    res = {}
    for ldata in linked_data:
        for sample in ldata["archive"]["data"].get("samples", []):
            lab_id = sample.get("lab_id")
            if not lab_id:
                continue
            res.setdefault(lab_id, []).append(
                (ldata["archive"]["data"], ldata["archive"]["metadata"])
            )
    return res


def get_all_JV(url, token, sample_ids, jv_type=ENTRY_TYPES["jv"]):
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    entries = query_all(url, token, "entries/query", query)
    entry_ids = [entry["entry_id"] for entry in entries]

    query = {
        "required": {
            "data": "*",
            "metadata": "*",
        },
        "owner": "visible",
        "query": {"entry_references.target_entry_id:any": entry_ids, "entry_type": jv_type},
        "pagination": {"page_size": 10000},
    }
    linked_data = query_all(url, token, "entries/archive/query", query)
    return _index_linked_data_by_sample(linked_data)


def get_all_measurements_except_JV(url, token, sample_ids):
    # collect the results of the sample, in this case it are all the annealing temperatures
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    entries = query_all(url, token, "entries/query", query)
    entry_ids = [entry["entry_id"] for entry in entries]

    query = {
        "required": {
            "data": "*",
            "metadata": "*",
        },
        "owner": "visible",
        "query": {
            "entry_references.target_entry_id:any": entry_ids,
            "section_defs.definition_qualified_name": ENTRY_TYPES["base_measurement"],
        },
        "pagination": {"page_size": 10000},
    }
    linked_data = query_all(url, token, "entries/archive/query", query)
    non_jv = [
        ldata
        for ldata in linked_data
        if "entry_type" in ldata["archive"]["metadata"]
        and "JV" not in ldata["archive"]["metadata"]["entry_type"]
    ]
    return _index_linked_data_by_sample(non_jv)


def get_all_eqe(url, token, sample_ids, eqe_type=ENTRY_TYPES["eqe"]):
    #
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    entries = query_all(url, token, "entries/query", query)
    entry_ids = [entry["entry_id"] for entry in entries]

    query = {
        "required": {
            "data": "*",
            "metadata": "*",
        },
        "owner": "visible",
        "query": {"entry_references.target_entry_id:any": entry_ids, "entry_type": eqe_type},
        "pagination": {"page_size": 10000},
    }
    linked_data = query_all(url, token, "entries/archive/query", query)
    return _index_linked_data_by_sample(linked_data)


def get_all_mppt(url, token, sample_ids, mppt_type=ENTRY_TYPES["mppt"]):
    #
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 100},
    }
    entries = query_all(url, token, "entries/query", query)
    entry_ids = [entry["entry_id"] for entry in entries]

    query = {
        "required": {
            "data": "*",
            "metadata": "*",
        },
        "owner": "visible",
        "query": {"entry_references.target_entry_id:any": entry_ids, "entry_type": mppt_type},
        "pagination": {"page_size": 100},
    }
    linked_data = query_all(url, token, "entries/archive/query", query)
    return _index_linked_data_by_sample(linked_data)


def get_processing_steps(url, token, sample_ids, process_type=ENTRY_TYPES["base_process"]):
    # collect the entry ids of the samples
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    entries = query_all(url, token, "entries/query", query)
    entry_ids = [entry["entry_id"] for entry in entries]

    query = {
        "required": {
            "data": "*",
        },
        "owner": "visible",
        "query": {
            "entry_references.target_entry_id:any": entry_ids,
            "section_defs.definition_qualified_name": process_type,
        },
        "pagination": {"page_size": 10000},
    }
    data = query_all(url, token, "entries/archive/query", query)
    data = list(map(lambda process: process["archive"]["data"], data))
    # delete entries for which "position_in_experimental_plan" is not defined, these are likely not proper processing steps
    data = [step for step in data if "positon_in_experimental_plan" in step]
    data.sort(key=lambda process: process["positon_in_experimental_plan"])
    return data


def get_efficiencies(url, token, sample_ids):
    query = {
        "required": {
            "results": {
                "properties": {"optoelectronic": {"solar_cell": {"efficiency": "*"}}},
                "eln": {"lab_ids": "*"},
            }
        },
        "query": {
            "results.eln.lab_ids:any": sample_ids,
            "results.properties.optoelectronic.solar_cell.efficiency:gt": "0",
        },
        "owner": "visible",
    }
    data = query_all(url, token, "entries/archive/query", query)
    # return dict with entries lab_id:efficiency
    return dict(
        map(
            lambda x: (
                x["archive"]["results"]["eln"]["lab_ids"][0],
                x["archive"]["results"]["properties"]["optoelectronic"]["solar_cell"]["efficiency"],
            ),
            data,
        )
    )
