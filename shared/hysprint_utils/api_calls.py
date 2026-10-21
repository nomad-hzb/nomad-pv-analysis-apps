# api_calls.py
# methods to access the nomad api

import getpass
import logging
import time
from urllib.parse import quote

import requests

from hysprint_utils.config import ENTRY_TYPES

logger = logging.getLogger(__name__)

# (connect, read) seconds for every request. Archive queries of a few thousand entries are
# slow, so the read timeout is generous; it only exists so a dead server cannot hang an app.
REQUEST_TIMEOUT = (10, 300)
DEFAULT_PAGE_SIZE = 10000
# Safety stop for the page loop (a server that keeps returning a next page forever).
MAX_PAGES = 1000


def _query_all(url, token, endpoint, query, timeout=REQUEST_TIMEOUT):
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
        response = requests.post(f"{url}/{endpoint}", headers=headers, json=query, timeout=timeout)
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


def edit_entry(url, token, entry_id, changes):
    """Patch fields on an existing entry's archive via NOMAD's own ELN-edit endpoint.

    changes: list of {"path": <dotted path into the archive, e.g.
    "data.results.0.T80">, "new_value": <value>, "action": "upsert"}
    ("action" defaults to "upsert" server-side if omitted).

    Raises requests.HTTPError on failure (400/403/404/422) - the response body
    carries NOMAD's own detail/validation-error text, which callers should
    surface as-is rather than replacing with a generic message.
    """
    response = requests.post(
        f"{url}/entries/{entry_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"changes": changes},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# retreive information about all uploads of current user
def get_all_uploads(url, token, number_of_uploads=20):
    response = requests.get(
        f"{url}/uploads",
        headers={"Authorization": f"Bearer {token}"},
        params=dict(page_size=number_of_uploads, order_by="upload_create_time", order="desc"),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["data"]


def get_all_batches_wth_data(url, token, entry_type):
    query = {
        "required": {"metadata": {"upload_id": "*"}},
        "owner": "visible",
        "query": {"entry_type": entry_type},
        "pagination": {"page_size": 10000},
    }

    data = _query_all(url, token, "entries/archive/query", query)
    upload_ids = list(set([u["upload_id"] for u in data]))
    query = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"entry_type": ENTRY_TYPES["batch"], "upload_id:any": upload_ids},
        "pagination": {"page_size": 10000},
    }
    data = _query_all(url, token, "entries/archive/query", query)

    return list(set([b["archive"]["data"]["lab_id"] for b in data]))


def get_template(url, token, upload_name, method):
    query = {
        "required": {
            "data": "*",
        },
        "owner": "visible",
        "query": {"upload_name": upload_name, "entry_type": method},
        "pagination": {"page_size": 100},
    }
    data = _query_all(url, token, "entries/archive/query", query)
    return data


def get_token(url, name=None):
    user = name if name is not None else input("Username")
    print("Passwort: \n")
    password = getpass.getpass()

    # Get a token from the api, login
    response = requests.post(
        f"{url}/auth/token", data=dict(username=user, password=password), timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_batch_ids(url, token, batch_type=ENTRY_TYPES["batch"]):
    query = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"entry_type": batch_type},
        "pagination": {"page_size": 10000},
    }
    data = _query_all(url, token, "entries/archive/query", query)
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
            response = requests.get(
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
    data = _query_all(url, token, "entries/archive/query", query)

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
    data = _query_all(url, token, "entries/archive/query", query)
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
    data = _query_all(url, token, "entries/archive/query", query)
    assert len(data) == 1, "Entry not found"
    return data[0]["archive"]["data"]


def get_sample_description(url, token, sample_ids):
    query = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    entries = _query_all(url, token, "entries/query", query)
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
    data = _query_all(url, token, "entries/query", query)
    assert len(data) == 1
    return data[0]["entry_id"]


def get_nomad_ids_of_entry(url, token, sample_id):  # give it a batch id
    # get al entries related to this batch id
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids": sample_id},
        "pagination": {"page_size": 100},
    }
    data = _query_all(url, token, "entries/query", query)
    assert len(data) == 1
    return data[0]["entry_id"], data[0]["upload_id"]


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
    for entry in _query_all(url, token, "entries/query", query):
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
    put_response = requests.put(
        f"{url}/uploads/{upload_id}/raw/",
        data={"wait_for_processing": False},
        headers=headers,
        files={"file": (filename, content, mime_type)},
        timeout=REQUEST_TIMEOUT,
    )
    put_response.raise_for_status()
    requests.post(
        f"{url}/uploads/{upload_id}/action/process", headers=headers, timeout=REQUEST_TIMEOUT
    )

    waited = 0.0
    while waited < max_wait:
        time.sleep(poll_interval)
        waited += poll_interval
        response = requests.get(
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
    response = requests.get(
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
    data = _query_all(url, token, "entries/query", query)

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
    data = _query_all(url, token, "entries/query", query)
    assert len(data) == 1, "Entry not found"
    return data[0]


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
    assert data and len(data) == 1, "No Setup found"
    return data[0]


def get_environment(url, token, entry_id):
    data = get_information(url, token, entry_id, "data.environment")
    assert data and len(data) == 1, "No Environment found"
    return data[0]


def get_samples(url, token, entry_id):
    data = get_information(url, token, entry_id, "data.samples.reference")
    assert data and len(data) > 0, "No Samples found"
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
    linked_data = _query_all(url, token, "entries/archive/query", query)
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
    entries = _query_all(url, token, "entries/query", query)
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
    linked_data = _query_all(url, token, "entries/archive/query", query)
    return _index_linked_data_by_sample(linked_data)


def get_all_measurements_except_JV(url, token, sample_ids):
    # collect the results of the sample, in this case it are all the annealing temperatures
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    entries = _query_all(url, token, "entries/query", query)
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
    linked_data = _query_all(url, token, "entries/archive/query", query)
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
    entries = _query_all(url, token, "entries/query", query)
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
    linked_data = _query_all(url, token, "entries/archive/query", query)
    return _index_linked_data_by_sample(linked_data)


def get_all_mppt(url, token, sample_ids, mppt_type=ENTRY_TYPES["mppt"]):
    #
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 100},
    }
    entries = _query_all(url, token, "entries/query", query)
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
    linked_data = _query_all(url, token, "entries/archive/query", query)
    return _index_linked_data_by_sample(linked_data)


def get_processing_steps(url, token, sample_ids, process_type=ENTRY_TYPES["base_process"]):
    # collect the entry ids of the samples
    query = {
        "required": {"metadata": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": sample_ids},
        "pagination": {"page_size": 10000},
    }
    entries = _query_all(url, token, "entries/query", query)
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
    data = _query_all(url, token, "entries/archive/query", query)
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
    data = _query_all(url, token, "entries/archive/query", query)
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
