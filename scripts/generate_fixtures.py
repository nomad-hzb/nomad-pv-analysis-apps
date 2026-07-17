"""
Generate test fixtures by fetching real data from NOMAD Oasis.

Usage:
    python scripts/generate_fixtures.py \\
        --url https://nomad-hzb-se.de/nomad-oasis/api/v1 \\
        --token YOUR_TOKEN \\
        --batch BATCH_ID \\
        --app TRPL_Analysis

Writes: tests/<app>/fixtures/api_responses.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))


def _fetch_trpl(url, token, batch_ids):
    from hysprint_utils.api_calls import get_all_eqe, get_ids_in_batch, get_sample_description

    sample_ids = list(get_ids_in_batch(url, token, batch_ids))
    descriptions = get_sample_description(url, token, sample_ids)
    raw = get_all_eqe(url, token, sample_ids, "HySprint_TimeResolvedPhotoluminescence")
    return {"sample_ids": sample_ids, "descriptions": descriptions, "measurements": raw}


def _fetch_xrd(url, token, batch_ids):
    from hysprint_utils.api_calls import get_all_eqe, get_ids_in_batch, get_sample_description

    sample_ids = list(get_ids_in_batch(url, token, batch_ids))
    descriptions = get_sample_description(url, token, sample_ids)
    raw = get_all_eqe(url, token, sample_ids, "HySprint_XRD_XY")
    return {"sample_ids": sample_ids, "descriptions": descriptions, "measurements": raw}


def _fetch_nmr(url, token, batch_ids):
    from hysprint_utils.api_calls import get_all_eqe, get_ids_in_batch, get_sample_description

    sample_ids = list(get_ids_in_batch(url, token, batch_ids))
    descriptions = get_sample_description(url, token, sample_ids)
    raw = get_all_eqe(url, token, sample_ids, "HySprint_Simple_NMR")
    return {"sample_ids": sample_ids, "descriptions": descriptions, "measurements": raw}


def _fetch_eqe(url, token, batch_ids):
    from hysprint_utils.api_calls import get_all_eqe, get_ids_in_batch, get_sample_description

    sample_ids = list(get_ids_in_batch(url, token, batch_ids))
    descriptions = get_sample_description(url, token, sample_ids)
    raw = get_all_eqe(url, token, sample_ids, "HySprint_EQEmeasurement")
    return {"sample_ids": sample_ids, "descriptions": descriptions, "measurements": raw}


def _fetch_abspl(url, token, batch_ids):
    from hysprint_utils.api_calls import get_all_eqe, get_ids_in_batch, get_sample_description

    sample_ids = list(get_ids_in_batch(url, token, batch_ids))
    descriptions = get_sample_description(url, token, sample_ids)
    raw = get_all_eqe(url, token, sample_ids, "HySprint_AbsPLMeasurement")
    return {"sample_ids": sample_ids, "descriptions": descriptions, "measurements": raw}


def _fetch_jv(url, token, batch_ids):
    from hysprint_utils.api_calls import get_all_JV, get_ids_in_batch, get_sample_description

    sample_ids = list(get_ids_in_batch(url, token, batch_ids))
    descriptions = get_sample_description(url, token, sample_ids)
    raw = get_all_JV(url, token, sample_ids)
    return {"sample_ids": sample_ids, "descriptions": descriptions, "measurements": raw}


def _fetch_mppt(url, token, batch_ids):
    from hysprint_utils.api_calls import get_all_mppt, get_ids_in_batch, get_sample_description

    sample_ids = list(get_ids_in_batch(url, token, batch_ids))
    descriptions = get_sample_description(url, token, sample_ids)
    raw = get_all_mppt(url, token, sample_ids)
    return {"sample_ids": sample_ids, "descriptions": descriptions, "measurements": raw}


FETCHERS = {
    "TRPL_Analysis": _fetch_trpl,
    "XRD_peak_finder": _fetch_xrd,
    "NMR_Analysis": _fetch_nmr,
    "EQE_Analysis": _fetch_eqe,
    "AbsPL_Analysis": _fetch_abspl,
    "JV-Analysis": _fetch_jv,
    "MPPT_Analysis": _fetch_mppt,
}


def _make_serialisable(obj):
    """Recursively convert non-JSON-serialisable objects to primitives."""
    if isinstance(obj, dict):
        return {k: _make_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serialisable(v) for v in obj]
    try:
        import numpy as np  # noqa: PLC0415

        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
    except ImportError:
        pass
    return obj


def main():
    parser = argparse.ArgumentParser(description="Generate NOMAD test fixtures")
    parser.add_argument("--url", required=True, help="NOMAD Oasis API URL")
    parser.add_argument("--token", required=True, help="NOMAD API token")
    parser.add_argument(
        "--batch", required=True, nargs="+", help="Batch ID(s) to fetch data for"
    )
    parser.add_argument(
        "--app",
        required=True,
        choices=list(FETCHERS.keys()),
        help="App to generate fixture for",
    )
    parser.add_argument(
        "--out",
        help="Output path (default: tests/<app>/fixtures/api_responses.json)",
    )
    args = parser.parse_args()

    fetcher = FETCHERS[args.app]
    print("Fetching %s data for batches: %s" % (args.app, args.batch))
    data = fetcher(args.url, args.token, args.batch)

    out_path = (
        Path(args.out)
        if args.out
        else Path(__file__).parent.parent / "tests" / args.app / "fixtures" / "api_responses.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    serialisable = _make_serialisable(data)
    with open(out_path, "w") as f:
        json.dump(serialisable, f, indent=2)

    print("Written to %s" % out_path)


if __name__ == "__main__":
    main()
