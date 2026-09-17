"""Import the eosl.date hardware catalog: vendor product families and their models.

eosl.date publishes no API — the server-rendered HTML tables below each family
page are the only interface. Every page carries up to three tables whose row
classes state the lifecycle status outright (``release-row-supported``,
``table-warning-row release-row-warning``, ``table-eol-row release-row-eol``),
and every cell declares its own column through ``data-label``, so columns are
read by role rather than by position.

Column roles, resolved from the declared header row and matched case- and
whitespace-insensitively:

* identity — ``Product``/``Product Name``, ``Model Number``/``Model Name``,
  ``Product Line``
* ``ga`` — ``Release Date``/``Launch Date``
* ``eos`` — a column naming end of sales: ``End of Sale(s) Date`` and
  ``End of Life Date`` (eosl.date's own glossary defines that column as the end
  of sales date, when a product is no longer sold)
* ``eol`` — the terminal support column, eosl.date's EOSL/LDOS:
  ``End of Support``, ``End of Support (EOSL)``, ``End of Support Date``,
  ``End of Service``, ``End of Service Date``

Every other column — ``EOL Announced``, warranty and discontinuance columns,
``Version Number`` — is carried verbatim in ``upstream``, so no published date
is lost and a future re-mapping never requires a re-fetch.

No date is ever invented. A dated value is either a ``<time datetime>``
attribute or a bare ``YYYY-MM-DD``; every other value (``TBD``,
``Not Announced``, an empty cell, or a support.apple.com URL standing in for an
unannounced deadline) becomes ``None``.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

from .importer import ROOT, dump

HARDWARE_SOURCE = "https://eosl.date/"
SITEMAP = "https://eosl.date/sitemap-coreapp-product-families.xml"
VERIFIER = "deterministic-eosl-date"
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/hardware.json"
USER_AGENT = "eoltracker/1.0 (+https://github.com/zarguell/eoltracker)"
TIMEOUT = (15, 60)
WORKERS = 2
REQUEST_PAUSE = 0.5
RETRY_DELAY = 5.0

# A family path is a category (which may itself be nested, such as
# `storage/san-switches`), `/vendor/`, a vendor and a family.
FAMILY_PATH = re.compile(
    r"^(?P<category>[a-z0-9][a-z0-9/-]*)/vendor/(?P<vendor>[^/]+)/(?P<family>[^/]+)/$")
SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Lifecycle values that mean "no date published"; none of them is a date.
SENTINELS = {"", "tbd", "tba", "not announced", "not available", "n/a", "na", "unknown", "none"}
# Row class -> published status. Rows without one of these are not model rows:
# these tables also carry advertisement rows.
ROW_STATUS = {
    "release-row-supported": "supported",
    "table-warning-row release-row-warning": "expiring",
    "table-eol-row release-row-eol": "eol",
}
# Column role -> the declared headers naming it, after normalization.
ROLE_HEADERS = (
    ("product", {"product", "productname"}),
    ("model", {"modelnumber", "modelname"}),
    ("line", {"productline"}),
    ("ga", {"releasedate", "launchdate"}),
    ("eos", {"endofsaledate", "endofsalesdate", "endoflifedate"}),
    ("eol", {"endofsupport", "endofsupport(eosl)", "endofsupportdate",
             "endofservice", "endofservicedate"}),
    # Not a milestone: the row's own identifier on the software-shaped families
    # (one row per released version), kept raw and used as the model fallback.
    # A build number is kept apart from it, being the less meaningful of the
    # two where a family publishes both.
    ("version", {"versionnumber", "version"}),
    ("build", {"buildnumber"}),
)
STATUS_ORDER = ("supported", "expiring", "eol")
MILESTONES = ("ga", "eos", "eossec", "eol")
# eosl.date renders relative support prose inside the same cell as the date.
RELATIVE_SUFFIX = re.compile(r"^(?P<date>.*?)\s*Support (?:ended|continues)\b.*$", re.S)


def _normalize(text):
    """Fold a header or data-label for comparison: no whitespace, lower case."""
    return re.sub(r"\s+", "", text).lower()


def _text(value):
    return re.sub(r"\s+", " ", value).strip()


def slugify(value):
    """An id slug: ASCII, lower case, hyphen separated and never empty.

    A character outside ASCII (such as the multiplication sign in
    ``MA-MOD-4×10`` or an accented letter) separates words rather than
    vanishing, so ``4×10`` and ``410`` cannot slugify alike.
    """
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    folded = "".join(char if char.isascii() else "-" for char in folded)
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def _date(value):
    """Return ``value`` when it is a real calendar day, else None.

    Any other returned value would be an invented date, and an impossible one
    such as ``2026-02-30`` would fail the record schema anyway.
    """
    if not DATE.fullmatch(value):
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def family_path(url):
    """The (category, vendor, family) of a same-origin family URL, else None."""
    path = url.split("?", 1)[0].split("#", 1)[0]
    if path.startswith(HARDWARE_SOURCE):
        path = path[len(HARDWARE_SOURCE):]
    elif "://" in path:
        return None
    return FAMILY_PATH.match(path.strip("/") + "/")


def family_url(match):
    """The canonical absolute family URL of a `family_path` match."""
    return "{}{}/vendor/{}/{}/".format(HARDWARE_SOURCE, match.group("category"),
                                       match.group("vendor"), match.group("family"))


class _Tables(HTMLParser):
    """Collect table rows and cells with their declared labels and times."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._header_cell = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table":
            self._table = {"headers": [], "rows": []}
        elif tag == "tr" and self._table is not None:
            self._row = {"class": attributes.get("class") or "", "cells": [], "header": []}
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {"label": attributes.get("data-label"), "text": "", "time": None,
                          "links": []}
            self._header_cell = tag == "th"
        elif tag == "time" and self._cell is not None:
            self._cell["time"] = attributes.get("datetime")
        elif tag == "a" and self._cell is not None and attributes.get("href"):
            self._cell["links"].append(attributes["href"])

    def handle_endtag(self, tag):
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table["headers"].extend(self._row["header"])
            self._table["rows"].append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._close_cell()

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data

    def _close_cell(self):
        cell, self._cell = self._cell, None
        text = _text(cell["text"])
        # "Apr. 30, 2026Support ended 4 months ago" keeps only the machine date.
        if cell["time"] is not None:
            match = RELATIVE_SUFFIX.match(text)
            if match:
                text = _text(match.group("date"))
        if self._header_cell:
            self._table["headers"].append(text)
        else:
            cell["text"] = text
            self._row["cells"].append(cell)


def _tables(html):
    parser = _Tables()
    parser.feed(html)
    parser.close()
    return parser.tables


def cell_value(cell):
    """The published date of one cell, or None when it publishes no date.

    ``None`` covers every unnamed case: an empty cell, a sentinel such as
    ``TBD`` or ``Not Announced``, and free text that is not a date at all.
    """
    if cell is None:
        return None
    value = _text(cell["time"] if cell["time"] is not None else cell["text"])
    if value.lower() in SENTINELS:
        return None
    return _date(value)


def _roles(headers, url):
    """Map normalized header -> role, rejecting a table whose shape drifted.

    A family table that lost its identity or terminal-support column is never
    published with silently missing dates: the drift raises here instead.
    """
    roles = {}
    for header in headers:
        name = _normalize(header)
        if not name:
            continue
        roles[name] = next((role for role, names in ROLE_HEADERS if name in names), None)
    if "product" not in roles.values() and "model" not in roles.values():
        raise ValueError(f"No product or model column in a table of {url}: {headers}")
    if "eol" not in roles.values():
        raise ValueError(f"No end of support column in a table of {url}: {headers}")
    return roles


def _first(cells, roles, role, nonempty=False):
    """The cell holding ``role``: the first declared column, else the first filled one.

    Two columns can name one role for identity (``Product`` beside
    ``Product Name``, the first often empty on HPE pages), so identity lookups
    ask for the first cell that actually carries a value. A date role is never
    doubled upstream, so dates keep the declared column.
    """
    cells_with_role = [cells[name] for name, mapped in roles.items()
                       if mapped == role and name in cells]
    if not nonempty:
        return cells_with_role[0] if cells_with_role else None
    return next((cell for cell in cells_with_role if cell["text"]), None)


def _identity(cells, roles):
    """The (product, model_number, product_line) triple naming one model.

    A family may publish a product without a model column (the HPE
    software-shaped pages), or, as one Apple row does, a model without a
    product; whichever exists stands in for the other so every published model
    still has an identity. On the software-shaped families a single product
    name covers one row per released version, and that version is what tells
    the rows apart, so it is the model number there.
    """
    product_cell = _first(cells, roles, "product", nonempty=True)
    model_cell = _first(cells, roles, "model", nonempty=True)
    line_cell = _first(cells, roles, "line", nonempty=True)
    version_cell = _first(cells, roles, "version", nonempty=True) or _first(
        cells, roles, "build", nonempty=True)
    product = product_cell["text"] if product_cell else ""
    model = model_cell["text"] if model_cell else ""
    if not model:
        model = version_cell["text"] if version_cell else ""
    return product or model, model or product, (line_cell["text"] if line_cell else "")


def _upstream(row, roles):
    """Every declared cell verbatim, including those no milestone claims."""
    upstream = {}
    for cell in row["cells"]:
        if not cell["label"]:
            continue
        upstream.setdefault(cell["label"], {
            "text": cell["text"],
            "datetime": cell["time"],
            "value": cell_value(cell),
            "role": roles.get(_normalize(cell["label"])),
            "links": list(cell["links"]),
        })
    return upstream


def parse_family_page(html, url):
    """Parse one family page: ``{family, vendor, source_url, models: [...]}``.

    ``url`` carries the identity the markup does not state outright (category,
    vendor and family slug) while the breadcrumb supplies the displayed names.
    Each model carries ``eossec: None``: eosl.date publishes no security
    support deadline, and claiming one would invent a contract never stated.
    """
    match = family_path(url)
    if not match:
        raise ValueError(f"Not a product family URL: {url}")
    crumbs = re.findall(r'<li class="breadcrumb-item[^"]*"[^>]*>(?:<a[^>]*>)?([^<]*)', html)
    vendor = _text(crumbs[1]) if len(crumbs) > 1 and _text(crumbs[1]) else match.group("vendor")
    family = _text(crumbs[2]) if len(crumbs) > 2 and _text(crumbs[2]) else match.group("family")

    models = []
    for table in _tables(html):
        if not any(_text(row["class"]) in ROW_STATUS for row in table["rows"]):
            continue
        headers = table["headers"] or next(
            (row["header"] for row in table["rows"] if row["header"]), [])
        roles = _roles(headers, url)
        for row in table["rows"]:
            status = ROW_STATUS.get(_text(row["class"]))
            if status is None:
                continue
            cells = {}
            for cell in row["cells"]:
                if cell["label"]:
                    cells.setdefault(_normalize(cell["label"]), cell)
            product, model, line = _identity(cells, roles)
            if not product:
                # A separator row: nothing published to name.
                continue
            models.append({
                "product": product,
                "model_number": model,
                "product_line": line,
                "ga": cell_value(_first(cells, roles, "ga")),
                "eos": cell_value(_first(cells, roles, "eos")),
                "eossec": None,
                "eol": cell_value(_first(cells, roles, "eol")),
                "status": status,
                "upstream": _upstream(row, roles),
            })
    return {"family": family, "vendor": vendor, "source_url": url, "models": models}


def parse_vendor_page(html):
    """The product family slugs a vendor overview page links, in page order.

    The visible dropdown items are ``href="#"`` placeholders, but every family
    carries its real path in ``data-family-url``; both are read, so either
    markup change keeps discovery working.
    """
    slugs = []
    for href in re.findall(r'data-family-url="([^"]+)"', html) + re.findall(
            r'<a[^>]*href="([^"]+)"', html):
        match = family_path(href)
        if match and match.group("family") not in slugs:
            slugs.append(match.group("family"))
    return slugs


def iter_family_urls(sitemap=None):
    """Yield every product family URL of the family sitemap, in sitemap order."""
    document = fetch(SITEMAP) if sitemap is None else sitemap
    for loc in SITEMAP_LOC.findall(document):
        match = family_path(loc)
        if match:
            yield family_url(match)


def fetch(url):
    """GET one page politely: identified, bounded, retried once on a network error."""
    last = None
    for attempt in range(2):
        try:
            response = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except requests.RequestException as error:
            last = error
            if attempt == 0:
                time.sleep(RETRY_DELAY)
    raise last


def merge_models(models):
    """Merge duplicate models and assign each one its published id.

    One model can appear in several families — a Cisco MDS switch is also a
    Dell EMC Connectrix-Cisco model — so models merge on
    ``(product_line, product, model_number)`` and every source URL is kept.
    Milestones only ever gain a value: two sources publishing different dates
    for one model is a contradiction to surface, never to settle by ordering.
    """
    merged = {}
    for model in models:
        product = _text(model["product"])
        if not product:
            raise ValueError(f"Hardware model without a product name: {model.get('source_url')}")
        identity = (_text(model["product_line"]), product, _text(model["model_number"]))
        existing = merged.get(identity)
        if existing is None:
            base = slugify(f"{model['vendor']}-{identity[2] or identity[1]}")
            if not base:
                raise ValueError(
                    f"Hardware model without a usable id: {product!r} in {model.get('source_url')}")
            merged[identity] = {
                "base": base, "identity": identity, "vendor": model["vendor"],
                "family": model["family"], "milestones": dict(model["milestones"]),
                "status": model["status"], "upstream": dict(model["upstream"]),
                "source_urls": [model["source_url"]],
            }
            continue
        _absorb(merged[identity], model)
    return _address(merged)


def _absorb(record, model):
    """Fold one more source's model into an already merged record."""
    for field in MILESTONES:
        value = model["milestones"][field]
        if value is None:
            continue
        current = record["milestones"][field]
        if current is None:
            record["milestones"][field] = value
        elif current != value:
            raise ValueError(
                f"Conflicting {field} for {record['identity']}: {current} != {value} "
                f"({record['source_urls'][0]} vs {model['source_url']})")
    if model["source_url"] not in record["source_urls"]:
        record["source_urls"].append(model["source_url"])
    record["upstream"].update(model["upstream"])
    record["status"] = max(record["status"], model["status"], key=STATUS_ORDER.index)


def _address(merged):
    """Give every merged model an id, resolving slug collisions deterministically.

    Two genuinely distinct published models can slugify alike (an Apple row
    whose model number and its sibling's disagree, a Brocade pair differing in
    whitespace). The collision is settled in identity order and against every
    id already taken, so the result never depends on fetch order and a
    generated suffix cannot land on another model's natural slug.
    """
    groups = {}
    for record in merged.values():
        groups.setdefault(record["base"], []).append(record)
    addressed = {}
    for base in sorted(groups):
        records = sorted(groups[base], key=lambda record: record["identity"])
        for position, record in enumerate(records):
            key = base if position == 0 else f"{base}-{position + 1}"
            while key in addressed:
                position += 1
                key = f"{base}-{position + 1}"
            record["id"] = key
            addressed[key] = record
    return addressed


def _record(record, checked):
    """The published hardware record for one merged model."""
    product_line, product, model_number = record["identity"]
    return {
        "$schema": RECORD_SCHEMA,
        "id": record["id"],
        "name": product,
        "category": "hardware",
        "vendor": record["vendor"],
        # The schema requires a non-empty product line, and a family that
        # publishes none is identified by its vendor.
        "product_line": product_line or record["vendor"],
        "family": record["family"],
        "model_number": model_number,
        "milestones": record["milestones"],
        "status": record["status"],
        "upstream": record["upstream"],
        "provenance": {
            "source_urls": record["source_urls"],
            "verifier": VERIFIER,
            "last_checked": checked,
        },
    }


def get_records(directory=None):
    """The committed hardware records, in slug order, for the catalog manifest."""
    directory = Path(directory) if directory is not None else ROOT / "data"
    return [json.loads(file.read_text(encoding="utf-8"))
            for file in sorted((directory / "hardware").glob("*.json"))]


def import_hardware():
    """Fetch every family page and write ``data/hardware/{id}.json``.

    Complete-or-nothing, like the software import: every page is fetched and
    parsed before the committed directory is touched, and a record's previous
    revision time is preserved while its content is unchanged, so a quiet
    source never looks freshly re-verified.
    """
    from .validation import validate_hardware

    urls = list(iter_family_urls())
    if not urls:
        raise ValueError("No product family URLs in the upstream sitemap")
    if len(set(urls)) != len(urls):
        raise ValueError("Duplicate product family URLs in the upstream sitemap")
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    # Two workers and a pause before each request: eosl.date is a small
    # server-rendered site that publishes no rate limit, so stay well inside one.
    def page(url):
        time.sleep(REQUEST_PAUSE)
        return url, fetch(url)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        pages = list(pool.map(page, urls))

    models = []
    for url, html in pages:
        parsed = parse_family_page(html, url)
        # A family page may legitimately publish nothing (ibm/cloud-object-storage).
        for model in parsed["models"]:
            models.append({
                "vendor": parsed["vendor"], "family": parsed["family"], "source_url": url,
                "product": model["product"], "model_number": model["model_number"],
                "product_line": model["product_line"],
                "milestones": {field: model[field] for field in MILESTONES},
                "status": model["status"], "upstream": model["upstream"],
            })
    merged = merge_models(models)

    destination = ROOT / "data" / "hardware"
    with tempfile.TemporaryDirectory(prefix="eoltracker-hardware-") as temp:
        staged = Path(temp)
        for key in sorted(merged):
            record = _record({**merged[key], "id": key}, checked)
            previous = destination / (key + ".json")
            if previous.exists():
                old = json.loads(previous.read_text(encoding="utf-8"))
                unchanged = {**record, "provenance": {**record["provenance"],
                                                      "last_checked": old["provenance"]["last_checked"]}}
                if old == unchanged:
                    record["provenance"]["last_checked"] = old["provenance"]["last_checked"]
            dump(staged / "hardware" / (key + ".json"), record)
        validate_hardware(staged)
        destination.mkdir(parents=True, exist_ok=True)
        for file in (staged / "hardware").glob("*.json"):
            shutil.copyfile(file, destination / file.name)
        for file in destination.glob("*.json"):
            if not (staged / "hardware" / file.name).exists():
                file.unlink()
    records = get_records()
    print(f"Imported {len(records)} hardware models from {len(urls)} product families")
    return records
