"""Count how many internet-exposed instances advertise a product, via Shodan.

A probe, not a catalog source. It exists so the decision in
``contributions/exposure-telemetry-design.md`` can be checked against a real
number by whoever holds a free Shodan key, and so the shape of any future
exposure feature is written down before it is built.

What it does and does not do:

* It calls ``GET https://api.shodan.io/shodan/host/count`` — the one Shodan
  endpoint that "does not consume query credits" — and reads the ``total`` and
  the requested facets.
* It **counts products, not versions**: a version-pinned query is refused by
  default, and ``--allow-version`` is the deliberate override.
  Shodan's ``version`` banner field is optional, is parsed from an advertised
  banner rather than observed device state, and a patched device routinely
  reports an older version, so a version-pinned figure would be a count of
  *reported versions*, not of end-of-life devices. The default refuses it.
* It never fetches, stores or prints an IP address, a hostname, a banner or a
  CVE. Shodan's terms forbid redistributing that content, and a published list
  of them is a targeting list. This tool returns a single attributed integer.

Usage::

    SHODAN_API_KEY=... python3 tools/exposure_count.py product:FortiOS
    SHODAN_API_KEY=... python3 tools/exposure_count.py --facets country:20,org:20 'product:nginx'
    SHODAN_API_KEY=... python3 tools/exposure_count.py --json product:"MikroTik RouterOS"

Without ``SHODAN_API_KEY`` in the environment it prints how to get a free key
and exits non-zero. It makes no network call without a key.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://api.shodan.io/shodan/host/count"
SOURCE = "Shodan"
SOURCE_URL = "https://www.shodan.io"
# The two facts a reader needs alongside any number, quoted from Shodan itself.
CAVEATS = (
    "Shodan /shodan/host/count, banner records rather than devices, over a "
    "rolling ~30-day index; Shodan states its crawlers 'don't do sweeps of IP "
    "ranges the same way a network scanner would'. This is not a census, and "
    "Shodan does not warrant that the information is accurate or reliable "
    "(terms 15.3(c))."
)
NO_KEY = (
    "No SHODAN_API_KEY in the environment. A free Shodan account is enough — "
    "register at https://account.shodan.io/register, copy the API key from "
    "https://account.shodan.io/ — and counting costs no query credits."
)


class ProbeError(RuntimeError):
    """The probe could not produce a count, and says why."""


def build_url(key, query, facets=None):
    """The count request for one query, with the facets Shodan should group by."""
    if not query or not query.strip():
        raise ProbeError("A query is required, for example product:FortiOS")
    parameters = {"key": key, "query": query}
    if facets:
        parameters["facets"] = facets
    return f"{ENDPOINT}?{urllib.parse.urlencode(parameters)}"


def is_version_query(query):
    """True when the query pins a version, which this probe refuses by default."""
    return any(token.strip().lower().startswith("version:") for token in query.split())


def fetch(url, timeout=30):
    """The count response, or a refusal that says what went wrong."""
    request = urllib.request.Request(url, headers={"User-Agent": "eoltracker-exposure-probe/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        if error.code == 401:
            raise ProbeError(f"Shodan rejected the API key (HTTP 401): {detail}") from error
        if error.code == 429:
            raise ProbeError("Shodan rate limit reached (HTTP 429); its documented limit is "
                             "one request per second") from error
        raise ProbeError(f"Shodan returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise ProbeError(f"Shodan was unreachable: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise ProbeError(f"Shodan returned a response that is not JSON: {error}") from error


def parse(payload, query, facets=None):
    """The count and its facets, with the basis the number is read against.

    Only the ``total`` and the facet buckets are read. A response that carries
    host records is reported as unexpected rather than partly used, so a future
    caller cannot accidentally retain a host it did not mean to.
    """
    if not isinstance(payload, dict) or "total" not in payload:
        raise ProbeError("Shodan's response carries no 'total' field")
    if payload.get("matches"):
        raise ProbeError("Shodan's count response unexpectedly carried host records; this probe "
                         "refuses to handle or retain them")
    total = payload["total"]
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ProbeError(f"Shodan's 'total' is not a count: {total!r}")
    groups = {}
    for name, buckets in (payload.get("facets") or {}).items():
        groups[name] = sorted(({"value": bucket.get("value"), "count": bucket.get("count")}
                               for bucket in buckets),
                              key=lambda bucket: (-(bucket["count"] or 0), str(bucket["value"])))
    return {
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "query": query,
        "facets": facets,
        "count": total,
        "unit": "banner records observed, not devices",
        "caveats": CAVEATS,
        "version_pinned": is_version_query(query),
        "groups": groups,
    }


def run(key, query, facets=None, allow_version=False, timeout=30):
    """One count, with the version-pinned refusal applied unless overridden."""
    if not key:
        raise ProbeError(NO_KEY)
    if is_version_query(query) and not allow_version:
        raise ProbeError("This query pins a version, which this probe refuses by default: "
                         "Shodan's version field is optional, is parsed from an advertised "
                         "banner, and a patched device commonly reports an older version, so "
                         "the number would count reported versions rather than end-of-life "
                         "devices. Pass --allow-version if you want it anyway.")
    return parse(fetch(build_url(key, query, facets), timeout), query, facets)


def main(argv=None):
    # The whole module docstring is the help: the refusals and the caveats are
    # the part a reader needs before running anything.
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", help='a Shodan query, e.g. product:FortiOS or "product:MikroTik RouterOS"')
    parser.add_argument("--facets", default="", help="facets to group by, e.g. country:20,org:20")
    parser.add_argument("--allow-version", action="store_true",
                        help="permit a version-pinned query (see the warning above)")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    try:
        result = run(os.environ.get("SHODAN_API_KEY", ""), args.query, args.facets,
                     args.allow_version, args.timeout)
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    print(f"{result['count']:,} {result['unit']} for `{result['query']}`")
    print(f"  as of this run, via {SOURCE} /shodan/host/count")
    for name, buckets in result["groups"].items():
        print(f"  by {name}:")
        for bucket in buckets[:10]:
            print(f"    {bucket['count']:>10,}  {bucket['value']}")
    print(f"  {result['caveats']}")
    print(f"  Data: {SOURCE} — {SOURCE_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
