"""Cisco classic IOS and NX-OS release-train lifecycle, from Cisco's own pages.

Two software families the catalog does not cover, each from the vendor's own
public lifecycle statement. Neither shadows an existing record: endoflife.date
publishes exactly one Cisco product (``cisco-ios-xe``), and IOS XE is a
different software family from classic IOS. Hardware is out of scope in both
cases — a hardware ``Last Date of Support`` is not a software end (rule 7).

**Cisco IOS** — the vendor's train inventory is read from two of its own pages,
then each train's page states the dates:

* the end-of-sale/end-of-life hub (``/c/en/us/support/eol/index.html``), whose
  ``IOS-NX-OS`` section files the classic IOS trains under the sub-header
  ``IOS 15 Software`` with the vendor's own status wording as the image alt
  (``End of Support``, ``End of Sale``);
* the IOS software releases catalog
  (``/c/en/us/products/ios-nx-os-software/ios-software-releases-listing.html``),
  which additionally names the trains the hub no longer lists.

A train's series page carries a ``birth-cert-table`` whose labelled rows are the
whole evidence: ``Series Release Date``, ``End-of-Sale Date`` and
``End-of-Support Date``, plus the vendor's own ``Status`` cell and lifecycle
sentence. A train the vendor has retired is served from ``/c/en/us/obsolete/``
as a **Retirement Notification** stating the same two labels, so a retired train
keeps its recorded dates instead of becoming undated.

``End-of-Support Date`` is the terminal date, not a security-only one. The
announcement for the Cisco 15.9(3)M Software Release states ``Last Date of
Support: OS SW — July 31, 2031`` and ``End-of-Sale Date: OS SW — July 28,
2026``, the same two values the 15.9M&T series page states (``31-JUL-2031``,
``28-JUL-2026``). So ``eol`` is filled from ``End-of-Support Date``, ``eos``
from ``End-of-Sale Date`` and ``ga`` from ``Series Release Date``; ``eossec``
stays null because these pages publish no security-only end. A train whose page
states only a series date (15.8M&T, ``Status: Available``) publishes its ``ga``
and no deadline rather than a deadline inferred from the vendor's cadence.

**Cisco NX-OS** — the vendor's lifecycle support statement for *Cisco NX-OS on
Cisco Nexus 9000* carries ``Table 2. NX-OS EoL Milestones`` with the columns
``NX-OS Major Release | EoSWM Date | EoVSS/LDoS`` and one row per major release
train (10.2(x) … 10.7(x)). The same page states the semantics: after EoSWM a
release "receives only PSIRT fixes", and at 54 months "it reaches the End of
Software Vulnerability/Security Support (EoVSS) milestone in the EOL process.
This milestone also aligns with the LDoS. Beyond this date, no support will be
provided for this major release." That is the mapping evidence, and it is why
``EoSWM`` never becomes a milestone: a maintenance end followed by an announced
security phase is exactly the case that must not fill a terminal date. ``eossec``
comes from the ``EoVSS`` half of the ``EoVSS/LDoS`` cell and ``eol`` from the
``LDoS`` half; where the vendor states one date for both (10.3(x)) the same date
fills both, because the page says the milestones align. No general-availability
date is published, so ``ga`` stays null — the page's "Q3 of each calendar year"
cadence is never turned into an FCS date.

Both records are bounded to what the vendor publishes: the IOS record is the
trains Cisco's own listings inventory, and the NX-OS record is the train table
of the Nexus 9000 lifecycle statement. Per-model and per-platform bulletins
(Nexus 7000 NX-OS 8.x, MDS NX-OS, hardware line cards) are hardware-family
notices outside both scopes; they are named in each report's limitations and
never folded into a train. Every row the source pages state is accounted in the
report: published, or excluded with the reason the page states.
"""
import re
from datetime import date, datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from . import net, sources, transaction
from .importer import ROOT

# The registry owns the ids and the pages: a record's provenance must name a
# source this checkout installs, and each collector reads its own verifier and
# page URLs from there rather than restating them. The IOS source registers its
# pages in the order it reads them, so the leading page is the hub and the
# catalog's URL comes from the registry's own page list — one declaration, no
# constant that could drift from what the registry publishes.
IOS = sources.source("import-cisco-ios")
NX_OS = sources.source("import-cisco-nx-os")
VERIFIER_IOS = IOS.verifier
VERIFIER_NX_OS = NX_OS.verifier
IOS_HUB_URL = IOS.pages[0].url
IOS_CATALOG_URL = next(url for url in IOS.urls if url != IOS_HUB_URL)
NX_OS_URL = NX_OS.pages[0].url
IOS_REPORT = IOS.report
NX_OS_REPORT = NX_OS.report
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/product.json"

PRODUCT_ID_IOS = "cisco-ios"
PRODUCT_ID_NX_OS = "cisco-nx-os"
UPSTREAM_CATEGORY = "os"

# The hub's section that files the networking software trains, and the
# sub-header inside it that scopes classic IOS (as opposed to IOS XE and IOS XR,
# which are separate software families). Both are the vendor's own wording.
HUB_SECTION = "IOS-NX-OS"
HUB_IOS_GROUP = "IOS 15 Software"

# The labelled rows of a train page, exactly as the vendor heads them. A page
# stating none of them is not a lifecycle page, and one stating an unexpected
# date in them refuses the parse rather than publishing a guess.
SERIES_DATE = "Series Release Date"
SALE_DATE = "End-of-Sale Date"
SUPPORT_DATE = "End-of-Support Date"
STATUS = "Status"
IOS_LABELS = (SERIES_DATE, SALE_DATE, SUPPORT_DATE)

# The NX-OS table's own caption and columns.
NX_OS_TABLE = "NX-OS EoL Milestones"
NX_OS_HEADERS = ("NX-OS Major Release", "EoSWM Date", "EoVSS/LDoS")
RELEASE_COLUMN = "NX-OS Major Release"
# End of Software Maintenance. Retained verbatim and validated, never mapped:
# the vendor states the release continues to receive PSIRT fixes past this date.
SECURITY_LABEL = "EoVSS"

# A cell that states no date. None of these is a date, and none becomes one.
NO_DATE = {"", "-", "–", "—", "n/a", "na", "tbd", "tba", "unknown"}
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
          "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
# The three date forms these pages state: the series page's `28-AUG-2013`, the
# retirement notice's `2015-01-27` and the NX-OS table's `Nov 30 2023`. A cell
# matching none of them is a parse failure, not an undated milestone.
DAY_MONTH = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$")
ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
TEXTUAL = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$")
FOOTNOTE = re.compile(r"\s*\*+\s*$")
ROW = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
CELL = re.compile(r"<(th|td)\b[^>]*>(.*?)</\1>", re.S | re.I)
TABLE = re.compile(r"<table\b[^>]*>.*?</table>", re.S | re.I)
THEAD = re.compile(r"<thead\b[^>]*>.*?</thead>", re.S | re.I)
CAPTION = re.compile(r"<caption\b[^>]*>(.*?)</caption>", re.S | re.I)
# The NX-OS document is a converted FrameMaker page: its table caption is the
# paragraph above the table (`Table 2.  NX-OS EoL Milestones`) and its header
# cells are `<td>` inside `<thead>`, not `<th>`.
CAPTION_PARAGRAPH = re.compile(r"<p\b[^>]*class=\"[^\"]*pTableCaptionCMT[^\"]*\"[^>]*>(.*?)</p>", re.S | re.I)
TABLE_NUMBER = re.compile(r"^Table\s+\d+\.?\s*", re.I)
TAG = re.compile(r"<[^>]+>")
ANCHOR = re.compile(r"<a\b[^>]*>.*?</a>", re.S | re.I)
SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
PAGE_TITLE = re.compile(r"<h1\b[^>]*\bid\s*=\s*\"fw-pagetitle\"[^>]*>(.*?)</h1>", re.S | re.I)
SMART_TITLE = re.compile(r"<h1\b[^>]*\bclass\s*=\s*\"[^\"]*smartTitle[^\"]*\"[^>]*>(.*?)</h1>",
                         re.S | re.I)
SUBTITLE = re.compile(r"<p\b[^>]*\bclass\s*=\s*\"[^\"]*smartSubTitle[^\"]*\"[^>]*>(.*?)</p>",
                      re.S | re.I)
BIRTH_CERT = re.compile(r"<table\b[^>]*\bclass\s*=\s*\"[^\"]*birth-cert-table[^\"]*\"[^>]*>(.*?)</table>",
                        re.S | re.I)
LIFECYCLE_STATEMENT = re.compile(
    r"<div\b[^>]*\bid\s*=\s*\"microLifecycleBlade\"[^>]*>(.*?)</div>", re.S | re.I)
RETIREMENT_ITEM = re.compile(r"<li>\s*<p>\s*<b>([^<]+?)</b>\s*:?\s*(.*?)</p>\s*</li>", re.S | re.I)
CATALOG_TRAIN = re.compile(
    r"<a\b[^>]*href=\"([^\"]+)\"[^>]*>(Cisco\s+IOS\s+Software\s+Releases?\s+[^<]+)</a>", re.S | re.I)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value):
    """One cell's visible text: tags dropped, entities decoded, whitespace folded."""
    return re.sub(r"\s+", " ", unescape(TAG.sub(" ", value or ""))).replace("\xa0", " ").strip()


def _page(url):
    """Fetch ``url`` through the shared HTTP layer; returns its final URL and text.

    The final URL matters: the vendor answers a train it no longer documents
    with a redirect to its generic category page, and following that silently
    would publish an undated train as if the vendor had stated nothing.
    """
    response = net.get(url)
    response.encoding = "utf-8"
    return response.url, response.text


def day_value(text, where):
    """One of the three stated date forms -> ``YYYY-MM-DD``, or None when undated.

    A cell that matches none of them is a parse failure: guessing here would
    publish a date no page states (rule 2).
    """
    text = FOOTNOTE.sub("", re.sub(r"\s+", " ", text or "").strip()).strip()
    if text.lower() in NO_DATE:
        return None
    match = ISO.fullmatch(text)
    if match:
        return _calendar(match.group(1), match.group(2), match.group(3), where, text)
    match = DAY_MONTH.fullmatch(text)
    if match:
        return _month_calendar(match.group(3), match.group(2), match.group(1), where, text)
    match = TEXTUAL.fullmatch(text)
    if match:
        return _month_calendar(match.group(3), match.group(1), match.group(2), where, text)
    raise ValueError(f"{where}: unrecognized date {text!r}")


def _month_calendar(year, month, day, where, text):
    """A named-month form; an unknown month name is a parse failure."""
    number = MONTHS.get(month.lower())
    if number is None:
        raise ValueError(f"{where}: unrecognized month {month!r} in {text!r}")
    return _calendar(year, number, day, where, text)


def _calendar(year, month, day, where, text):
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        raise ValueError(f"{where}: not a calendar date: {text!r}") from None


def train_id(name):
    """The stable id of one IOS train, from the vendor's own name.

    ``15.9 M & T`` and ``Cisco IOS Software Releases 15.9M&T`` are the same
    train and normalize to ``15.9mt``; ``15.2 E``, ``15.2S`` and ``15.2M&T``
    stay distinct (``15.2e``, ``15.2s``, ``15.2mt``), so a permalink names a
    train and never a spelling of it.
    """
    text = re.sub(r"(?i)^Cisco\s+IOS\s+Software\s+Releases?\s+", "", (name or "").strip())
    text = re.sub(r"(?i)^Cisco\s+IOS\s+", "", text)
    text = re.sub(r"\s*&\s*", "", text)
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[^a-z0-9.]+", "", text.lower())


def major_id(name):
    """The stable id of one NX-OS major release: ``10.3(x)`` -> ``10.3``."""
    match = re.fullmatch(r"(\d+\.\d+)\s*\(x\)", (name or "").strip())
    if not match:
        raise ValueError(f"Unrecognized NX-OS release train {name!r}")
    return match.group(1)


def _table_blocks(page):
    """Every table on the page as ``(caption, headers, rows)``.

    A table's columns are read from its own header — a ``<thead>`` row (whose
    cells may be ``<td>``, as the converted NX-OS document writes them) or a
    leading all-``<th>`` row — so a reshaped table refuses the parse instead of
    letting a column be read under the wrong name. The caption is the table's
    own ``<caption>``, else the ``pTableCaptionCMT`` paragraph that precedes it.
    """
    captions = {match.end(): _text(match.group(1)) for match in CAPTION_PARAGRAPH.finditer(page)}
    blocks = []
    for match in TABLE.finditer(page):
        block = match.group(0)
        caption = CAPTION.search(block)
        if caption is not None:
            heading = _text(caption.group(1))
        else:
            preceding = [text for end, text in captions.items() if end <= match.start()]
            heading = TABLE_NUMBER.sub("", preceding[-1]).strip() if preceding else ""
        head = THEAD.search(block)
        headers = []
        if head is not None and ROW.findall(head.group(0)):
            headers = [_text(value) for _, value in CELL.findall(ROW.findall(head.group(0))[0])]
        rows, seen_header = [], False
        for row in ROW.findall(block):
            cells = [(kind.lower(), _text(value)) for kind, value in CELL.findall(row)]
            if not cells:
                continue
            if head is not None and row in head.group(0):
                continue
            if head is None and not seen_header and all(kind == "th" for kind, _ in cells):
                headers = [value for _, value in cells]
                seen_header = True
                continue
            rows.append([value for _, value in cells])
        blocks.append({"caption": heading, "headers": headers, "rows": rows})
    return blocks


class _Hub(HTMLParser):
    """The end-of-sale/end-of-life hub: its ``seoli-container`` sections and rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.sections = []
        self.section = None
        self.base = 0
        self.row = None
        self.depth = 0
        self.link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append(tag)
        if (tag == "section" and self.section is None
                and "seoli-container" in (attrs.get("class") or "")):
            self.section = {"id": attrs.get("id") or "", "heading": "", "rows": []}
            self.base = len(self.stack)
            return
        if self.section is None:
            return
        classes = attrs.get("class") or ""
        if tag == "h3" and not self.section["heading"] and self.stack[-2:-1] == ["div"]:
            self.link = "heading"
        elif tag == "li":
            self.depth += 1
            if self.depth == 1:
                self.row = {"text": "", "href": "", "alt": "", "subheader": False}
        elif tag == "a" and self.row is not None and not self.row["href"]:
            self.row["href"] = attrs.get("href") or ""
            self.link = "row"
        elif tag == "img" and self.row is not None and not self.row["alt"]:
            self.row["alt"] = attrs.get("alt") or ""
        if tag == "li" and self.depth == 1 and "seoli-sub-header" in classes:
            self.row["subheader"] = True
            self.link = "row"

    def handle_endtag(self, tag):
        while self.stack and self.stack.pop() != tag:
            pass
        if self.section is None:
            return
        if tag == "h3" and self.link == "heading":
            self.link = None
        elif tag == "a" and self.link == "row":
            self.link = None
        elif tag == "li":
            if self.depth == 1 and self.row is not None:
                self.section["rows"].append(self.row)
                self.row = None
                self.link = None
            self.depth = max(0, self.depth - 1)
        elif tag == "section" and len(self.stack) < self.base:
            self.sections.append(self.section)
            self.section = None

    def handle_data(self, data):
        # Every row's visible text is captured, not only an anchor's: the hub
        # also files plain rows (a product family's release cadence list), and a
        # row the report accounts for must be named as the vendor states it.
        if self.section is None or self.row is None:
            return
        self.row["text"] += data


def parse_hub(page):
    """The hub's sections; every row of every section is returned for accounting.

    ``IOS-NX-OS`` is the only section this source reads. The others are returned
    with their row counts so the report can state that the whole page was read:
    the hub files hardware families, collaboration endpoints and security
    products too, and none of them is classic IOS software (rule 7).
    """
    parser = _Hub()
    parser.feed(SCRIPT.sub("", page))
    if not parser.sections:
        raise ValueError(f"The Cisco end-of-life listing states no sections: {IOS_HUB_URL}")
    sections = []
    for section in parser.sections:
        group = ""
        rows = []
        for row in section["rows"]:
            text = re.sub(r"\s+", " ", unescape(row["text"])).strip()
            if row["subheader"]:
                group = text
                continue
            rows.append({"group": group, "name": text, "href": row["href"], "status": row["alt"]})
        sections.append({"id": section["id"], "rows": rows})
    return sections


def parse_catalog(page):
    """The IOS releases catalog's train rows: ``(name, url)`` in page order."""
    rows = []
    for match in CATALOG_TRAIN.finditer(SCRIPT.sub("", page)):
        name = re.sub(r"\s+", " ", unescape(match.group(2))).strip()
        href = unescape(match.group(1))
        rows.append({"name": name, "href": href})
    if not rows:
        raise ValueError(f"The Cisco IOS releases page states no release trains: {IOS_CATALOG_URL}")
    return rows


def ios_inventory(hub_page, catalog_page):
    """Every IOS train the two vendor pages inventory.

    Returns ``(trains, hub_rows, catalog_rows, excluded, duplicates)``. A train's
    identity is its normalized id, so the catalog's ``Cisco IOS Software
    Releases 15.3M&T`` and the hub's ``15.3 M & T`` reconcile to one train; the
    hub's row wins, because it carries the vendor's current status wording as
    well as the train's own name.

    Every row of both listings is accounted for, and every row the hub files
    under another section or group is reported with the reason it states no
    classic IOS train lifecycle — the hub also inventories hardware families,
    collaboration endpoints and the other IOS software families (rule 6, rule 7).
    """
    hub_rows, trains, seen, excluded = [], {}, {}, []
    for section in parse_hub(hub_page):
        for row in section["rows"]:
            hub_rows.append({**row, "section": section["id"]})
            if section["id"] != HUB_SECTION:
                excluded.append({
                    "listing": IOS_HUB_URL, "section": section["id"], "group": row["group"],
                    "row": row["name"] or row["href"],
                    "reason": f"the hub files this row under the {section['id']!r} section, not "
                              f"the IOS/NX-OS software section: it states no classic IOS "
                              f"release-train lifecycle"})
                continue
            if not row["href"] or "/ios-nx-os-software/" not in row["href"]:
                excluded.append({
                    "listing": IOS_HUB_URL, "section": section["id"], "group": row["group"],
                    "row": row["name"] or row["href"],
                    "reason": "the hub row is a section link, not a release train: it states no "
                              "train lifecycle"})
                continue
            if row["group"] != HUB_IOS_GROUP:
                excluded.append({
                    "listing": IOS_HUB_URL, "section": section["id"], "group": row["group"],
                    "row": row["name"],
                    "reason": f"the hub files this row under the vendor's {row['group']!r} group: "
                              f"it is not classic IOS software, and its own family scope is not "
                              f"this source's"})
                continue
            identifier = train_id(row["name"])
            if not identifier:
                excluded.append({"listing": IOS_HUB_URL, "section": section["id"],
                                 "group": row["group"], "row": row["name"],
                                 "reason": "the row states no release-train identity"})
                continue
            if identifier in trains:
                excluded.append({"listing": IOS_HUB_URL, "section": section["id"],
                                 "group": row["group"], "row": row["name"],
                                 "reason": f"duplicate hub row for train {identifier!r}"})
                continue
            trains[identifier] = {"id": identifier, "name": row["name"], "listing": "hub",
                                  "url": _absolute(row["href"]), "hub_status": row["status"]}
    catalog_rows = parse_catalog(catalog_page)
    duplicates = 0
    for row in catalog_rows:
        identifier = train_id(row["name"])
        if not identifier:
            excluded.append({"listing": IOS_CATALOG_URL, "row": row["name"],
                             "reason": "the row states no release-train identity"})
            continue
        seen[identifier] = seen.get(identifier, 0) + 1
        if identifier in trains:
            duplicates += 1
            continue
        trains[identifier] = {"id": identifier, "name": row["name"], "listing": "catalog",
                              "url": _absolute(row["href"]), "hub_status": ""}
    ordered = sorted(trains.values(), key=lambda train: (train["listing"] != "hub", train["id"]))
    return ordered, hub_rows, catalog_rows, excluded, duplicates


def _absolute(href):
    """A hub-relative link as an absolute cisco.com URL."""
    if href.startswith("http"):
        return href
    return "https://www.cisco.com" + (href if href.startswith("/") else "/" + href)


def parse_series(page, where):
    """One train page -> ``(title, cells, statement)``; refuses a reshaped table.

    Both page shapes the vendor serves end in the same three labels, so they are
    read as labelled pairs: the support series page's ``birth-cert-table``
    (``<th>End-of-Support Date</th><td>31-AUG-2025</td>``) and the retirement
    notice's ``smartListing`` (``<b>End-of-Sale Date</b>: 2017-03-01``).
    """
    body = SCRIPT.sub("", page)
    title = PAGE_TITLE.search(body) or SMART_TITLE.search(body)
    if title is None:
        raise ValueError(f"{where}: page states no title")
    title = _text(title.group(1))
    retirement = "Retirement Notification" in title
    if retirement:
        title = re.sub(r"\s*-\s*Retirement Notification\s*$", "", title)
    certificate = BIRTH_CERT.search(body)
    cells, statement = {}, ""
    if certificate is not None:
        for row in ROW.findall(certificate.group(1)):
            pairs = CELL.findall(row)
            if len(pairs) != 2 or pairs[0][0].lower() != "th" or pairs[1][0].lower() != "td":
                continue
            label = _text(pairs[0][1])
            value = _text(ANCHOR.sub(" ", pairs[1][1]))
            if label:
                cells[label] = value
        blade = LIFECYCLE_STATEMENT.search(certificate.group(1))
        if blade is not None:
            statement = _text(blade.group(1))
    if retirement:
        for label, value in RETIREMENT_ITEM.findall(body):
            label, value = _text(label), _text(value)
            if label in IOS_LABELS:
                cells[label] = value
        subtitle = SUBTITLE.search(body)
        statement = _text(subtitle.group(1)) if subtitle is not None else statement
    if cells and set(cells) == {STATUS}:
        raise ValueError(f"{where}: page states a status but no lifecycle dates")
    if not cells:
        raise ValueError(f"{where}: page states no lifecycle labels")
    for label in cells:
        if label not in IOS_LABELS + (STATUS,):
            raise ValueError(f"{where}: unexpected lifecycle label {label!r}")
    return title, cells, statement, retirement


def page_release(train, title, cells, statement, page_url=None):
    """One train's release row, derived from the labels its own page states.

    ``page_url`` is the URL the fetch actually landed on: a retired train's
    series URL redirects to its retirement notice under ``/obsolete/``, and the
    record names the page a reader can open to check the row.
    """
    name = re.sub(r"\s+", " ", title).strip() or train["name"]
    where = f"Cisco IOS {train['id']}"
    milestones = {
        "ga": day_value(cells.get(SERIES_DATE, ""), f"{where} {SERIES_DATE}"),
        "eos": day_value(cells.get(SALE_DATE, ""), f"{where} {SALE_DATE}"),
        "eossec": None,
        "eol": day_value(cells.get(SUPPORT_DATE, ""), f"{where} {SUPPORT_DATE}"),
    }
    if all(value is None for value in milestones.values()):
        raise ValueError(f"{where}: page states no dated milestone")
    upstream = {"name": name, "cells": cells, "table": title,
                "page": page_url or train["url"]}
    if statement:
        upstream["lifecycle_statement"] = statement
    if train["hub_status"]:
        upstream["hub_status"] = train["hub_status"]
    return {"id": train["id"], "name": name, "milestones": milestones, "upstream": upstream}


def validate_ios_record(record):
    """Rebuild every stored train from its own published cells, offline.

    A record's cells are the whole evidence: the train identity and all three
    milestones re-derive from them, so a file whose dates no longer follow the
    labels it stores is never published.
    """
    if record["provenance"]["verifier"] != VERIFIER_IOS:
        raise ValueError("Invalid Cisco IOS source identity")
    seen = set()
    for release in record["releases"]:
        cells = release.get("upstream", {}).get("cells")
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"Cisco IOS release without source cells: {release['id']}")
        for label in cells:
            if label not in IOS_LABELS + (STATUS,):
                raise ValueError(f"{record['id']}: release {release['id']} stores an unexpected "
                                 f"label {label!r}")
        train = {"id": release["id"], "name": release["upstream"].get("name", ""),
                 "url": release["upstream"].get("page", ""), "hub_status": ""}
        expected = page_release(train, release["upstream"].get("table", ""), cells,
                                release["upstream"].get("lifecycle_statement", ""),
                                release["upstream"].get("page", ""))
        if release["id"] in seen or train_id(release["name"]) != release["id"]:
            raise ValueError(f"{record['id']}: release {release['id']} does not name its own "
                             f"train: {release['name']!r}")
        seen.add(release["id"])
        if release["name"] != expected["name"] or release["milestones"] != expected["milestones"]:
            raise ValueError(f"{record['id']}: release {release['id']} contradicts its stored cells")
        if release["upstream"].get("in_source") not in (None, False):
            raise ValueError(f"{record['id']}: release {release['id']} carries an invalid "
                             f"retention marker")


def parse_lifecycle_page(page):
    """The NX-OS statement's tables -> ``(releases, excluded)``; no row is dropped.

    Only the ``NX-OS EoL Milestones`` table defines train lifecycle. The page's
    release-type taxonomy table is returned as excluded rows with the reason it
    states no train dates, so both tables are accounted for.
    """
    tables = _table_blocks(page)
    if not tables:
        raise ValueError(f"The Cisco NX-OS lifecycle statement states no tables: {NX_OS_URL}")
    releases, excluded, seen = [], [], set()
    found = False
    for table in tables:
        heading = table["caption"]
        if heading != NX_OS_TABLE:
            excluded.extend(
                {"table": heading or "untitled",
                 "row": " | ".join(cells[:2]),
                 "reason": "not the NX-OS EoL Milestones table: this row states a release "
                           "taxonomy, not a major-release lifecycle date"}
                for cells in table["rows"])
            continue
        found = True
        if tuple(table["headers"]) != NX_OS_HEADERS:
            raise ValueError(f"Unexpected {NX_OS_TABLE} headers: {table['headers']}")
        for cells in table["rows"]:
            if len(cells) != len(NX_OS_HEADERS):
                raise ValueError(f"{NX_OS_TABLE} row has {len(cells)} cells for "
                                 f"{len(NX_OS_HEADERS)} columns: {cells[:1]}")
            row = dict(zip(NX_OS_HEADERS, cells))
            name = row[RELEASE_COLUMN].strip()
            identifier = major_id(name)
            where = f"Cisco NX-OS {identifier}"
            if identifier in seen:
                excluded.append({"table": heading, "row": name,
                                 "reason": f"duplicate train row for release {identifier!r}"})
                continue
            seen.add(identifier)
            # EoSWM is validated as a stated date and retained verbatim; the
            # vendor states the train keeps receiving PSIRT fixes past it, so it
            # never becomes a milestone.
            day_value(row["EoSWM Date"], f"{where} EoSWM")
            halves = [half.strip() for half in row[SECURITY_LABEL + "/LDoS"].split("/")]
            if len(halves) > 2 or not halves[0]:
                raise ValueError(f"{where}: unrecognized EoVSS/LDoS cell "
                                 f"{row[SECURITY_LABEL + '/LDoS']!r}")
            security = day_value(halves[0], f"{where} EoVSS")
            support = day_value(halves[-1], f"{where} LDoS")
            if security is None or support is None:
                raise ValueError(f"{where}: EoVSS/LDoS states no date: "
                                 f"{row['EoVSS/LDoS']!r}")
            releases.append({
                "id": identifier,
                "name": f"Cisco NX-OS {identifier}(x)",
                "milestones": {"ga": None, "eos": None, "eossec": security, "eol": support},
                "upstream": {"name": name, "cells": row, "table": heading},
            })
    if not found:
        raise ValueError(f"The Cisco NX-OS statement states no {NX_OS_TABLE} table")
    if not releases:
        raise ValueError(f"The {NX_OS_TABLE} table produced no releases")
    return releases, excluded


def validate_nx_os_record(record):
    """Rebuild every stored train from its own published cells, offline."""
    if record["provenance"]["verifier"] != VERIFIER_NX_OS:
        raise ValueError("Invalid Cisco NX-OS source identity")
    seen = set()
    for release in record["releases"]:
        cells = release.get("upstream", {}).get("cells")
        if not isinstance(cells, dict) or set(cells) != set(NX_OS_HEADERS):
            raise ValueError(f"Cisco NX-OS release without source cells: {release['id']}")
        if release["id"] in seen or major_id(cells[RELEASE_COLUMN]) != release["id"]:
            raise ValueError(f"{record['id']}: release {release['id']} does not name its own "
                             f"train: {cells[RELEASE_COLUMN]!r}")
        seen.add(release["id"])
        parsed, _ = parse_lifecycle_page(
            "<table><caption>" + NX_OS_TABLE + "</caption><tr>"
            + "".join(f"<th>{head}</th>" for head in NX_OS_HEADERS) + "</tr><tr>"
            + "".join(f"<td>{cells[head]}</td>" for head in NX_OS_HEADERS) + "</tr></table>")
        expected = parsed[0]
        if (release["name"] != expected["name"]
                or release["milestones"] != expected["milestones"]
                or release["upstream"].get("table") != NX_OS_TABLE
                or release["upstream"].get("in_source") not in (None, False)):
            raise ValueError(f"{record['id']}: release {release['id']} contradicts its stored cells")


def retained(release):
    """A committed train the current pages no longer state, marked as such.

    The row is republished from its own stored cells, so retention can never
    introduce a date the vendor did not publish; the marker says only that this
    fetch did not state the train. Absence from a page is not an end of life.
    """
    return {**release, "upstream": {**release["upstream"], "in_source": False}}


def combine_releases(fresh, committed, source_name):
    """The complete train snapshot: this fetch's rows plus retained history."""
    if committed is None:
        return list(fresh), []
    ids = {release["id"] for release in fresh}
    kept = [retained(release) for release in committed["releases"] if release["id"] not in ids]
    return (fresh + kept,
            [{"id": release["id"], "name": release["name"],
              "reason": f"the current {source_name} pages do not state this train; the committed "
                        f"row and its dates are retained"} for release in kept])


def _record(product_id, name, labels, releases, source_url, checked):
    """One published software record for a train snapshot."""
    return {
        "$schema": RECORD_SCHEMA,
        "id": product_id,
        "name": name,
        "category": "software",
        "upstream_category": UPSTREAM_CATEGORY,
        # Cisco documents release trains, never a CPE for one; an invented
        # identifier would be a claim the source does not make.
        "identifiers": [],
        # The vendor column wording each mapped milestone was read from.
        "labels": labels,
        "links": {"html": source_url},
        "releases": releases,
        "provenance": {"source_url": source_url, "verifier": verifier_for(product_id),
                       "last_checked": checked, "upstream_modified": None},
    }


def verifier_for(product_id):
    """The registered verifier owning ``product_id``."""
    if product_id == PRODUCT_ID_IOS:
        return VERIFIER_IOS
    if product_id == PRODUCT_ID_NX_OS:
        return VERIFIER_NX_OS
    raise ValueError(f"No Cisco software source owns {product_id!r}")


def committed_record(root, product_id, name):
    """The committed record for one Cisco product, refusing a foreign one."""
    return transaction.committed_product_record(root, product_id, verifier_for(product_id),
                                                VALIDATORS[product_id], name)


def publish_record(record, report, root, report_name):
    """Stage the record beside the committed catalog, validate, then replace it."""
    return transaction.publish_product_record(record, report, root, report_name)


def _milestone_counts(releases):
    """How many published trains state each milestone — the honest date coverage."""
    return {key: sum(1 for release in releases if release["milestones"][key])
            for key in ("ga", "eos", "eossec", "eol")}


def ios_report_for(releases, excluded, kept, hub_rows, catalog_rows, duplicates, checked):
    """The per-row accounting the IOS source publishes beside its record.

    The two listings are counted separately — a row in each is two source rows
    and one train — and ``rows.seen`` is exactly ``hub_page_rows +
    catalog_rows``, so a reader can add up the report rather than trust its
    arithmetic. ``trains`` counts the distinct trains both listings reconcile
    to; ``published`` plus ``excluded`` trains is that count plus the retained
    history, which the report states separately so a reader can check it.
    """
    by_train = [entry for entry in excluded if "id" in entry]
    by_row = len(excluded) - len(by_train)
    fresh = len(releases) - len(kept)
    return {
        "source_url": IOS_HUB_URL,
        "catalog_url": IOS_CATALOG_URL,
        "verifier": VERIFIER_IOS,
        "checked_at": checked,
        "record_scope": ("Cisco IOS release trains: one software record with one release per "
                         "train, from the vendor's own end-of-sale/end-of-life hub and IOS "
                         "software releases listing, at the day precision the train pages state"),
        "rows": {
            "seen": len(hub_rows) + len(catalog_rows),
            "hub_page_rows": len(hub_rows),
            "catalog_rows": len(catalog_rows),
            "duplicate_rows": duplicates,
            "trains": fresh + len(by_train),
            "published_fresh": fresh,
            "excluded_trains": len(by_train),
            "excluded_listing_rows": by_row,
            "excluded": len(excluded),
            "published": len(releases),
            "retained": len(kept),
            "milestones": _milestone_counts(releases),
        },
        "excluded": excluded,
        "retained": kept,
        "total_records": 1,
        "limitations": [
            "Hardware is not covered: Cisco announces a hardware model's End-of-Sale and Last "
            "Date of Support in the same bulletin format, and a hardware Last Date of Support is "
            "not a software end. Those per-model notices are a hardware scope (AGENTS.md rule 7) "
            "and no hardware record is published here.",
            "IOS XE (XE 3E/16/17) and IOS XR trains share the hub section but are different "
            "software families; they are reported as excluded rows, and endoflife.date's "
            "cisco-ios-xe record already covers IOS XE.",
            "The record is the trains Cisco's own listing pages inventory. A train whose support "
            "page resolves to the generic IOS/NX-OS category is reported as an excluded row with "
            "that page-level reason — an absent page is not an assertion that no date exists, and "
            "that exclusion is what to re-check if the vendor later publishes one.",
            "eossec is absent throughout: the train pages publish a terminal End-of-Support Date "
            "and no separate security-support-only end.",
            "A train the vendor lists but states no deadline for (15.8M&T, Status: Available) "
            "publishes its series date and no deadline; no date is derived from the vendor's "
            "release cadence.",
            "No date is read from a bulletin's per-model milestone table into a train release: "
            "those tables describe the model, and every train date here is a labelled cell of the "
            "train's own page.",
            "The hub's rows outside the IOS/NX-OS software section are enumerated as excluded "
            "rows with the section they were filed under, so the page is accounted for as a whole "
            "rather than read only where it agrees with this scope.",
        ],
    }


def nx_os_report_for(releases, excluded, kept, tables, checked):
    """The per-row accounting the NX-OS source publishes beside its record."""
    return {
        "source_url": NX_OS_URL,
        "verifier": VERIFIER_NX_OS,
        "checked_at": checked,
        "record_scope": ("Cisco NX-OS major release trains: one software record with one release "
                         "per major release of the vendor's Software Lifecycle Support Statement "
                         "for Cisco NX-OS on Cisco Nexus 9000, at the day precision that table "
                         "states"),
        "rows": {
            "page_tables": len(tables),
            "seen": sum(len(table["rows"]) for table in tables),
            "published": len(releases),
            "retained": len(kept),
            "excluded": len(excluded),
            "milestones": _milestone_counts(releases),
        },
        "excluded": excluded,
        "retained": kept,
        "total_records": 1,
        "limitations": [
            "The vendor publishes this train table for Cisco NX-OS on Cisco Nexus 9000 only. "
            "Other NX-OS trains are announced per platform in per-family bulletins (Nexus 7000 "
            "NX-OS 8.x, MDS NX-OS 9.2(2), Nexus 3000/9000 7.0(3)/9.x) and are not collected, so "
            "this record is the vendor's train-level lifecycle statement, not every NX-OS "
            "announcement in existence.",
            "ga is absent: the table publishes no general-availability date, and the page's "
            "'a new major release will be launched in Q3 of each calendar year' cadence is a "
            "policy statement, never a date (AGENTS.md rule 2).",
            "EoSWM (End of Software Maintenance) is retained verbatim as a cell and never mapped: "
            "the same page states a major release past that date 'receives only PSIRT fixes', so "
            "it is a maintenance end, not a terminal or security-only end.",
            "eos is absent: the table publishes no end-of-sale column, and the page's End-of-Sale "
            "milestones belong to hardware/product bulletins.",
            "A single EoVSS/LDoS date (10.3(x)) fills both eossec and eol only because the page "
            "states the two milestones align and that no support is provided beyond that date; a "
            "split cell (10.2(x)) fills each from its own half.",
            "The footnote marker on 10.3(x) ('will be extended to support EX platforms till "
            "their Last Date of Support (LDOS)') is kept verbatim in the cell and never read as a "
            "software date: the extension is scoped to EX platforms by the vendor's own note.",
            "Hardware Last Date of Support is not a software end: the same page directs readers "
            "to the hardware EoL announcement for hardware milestones, and no hardware record is "
            "published here.",
        ],
    }


def import_ios(directory=None):
    """Fetch the Cisco IOS listings and publish the ``cisco-ios`` record.

    Complete-or-nothing: the listings and every train page are read, the fetched
    snapshot is combined with the trains the vendor no longer states, staged
    beside the committed catalog and validated there before anything is written.
    A parse failure, a reshaped table or an inconsistent catalog leaves every
    committed file untouched.
    """
    root = Path(directory) if directory is not None else ROOT / "data"
    # The committed ownership check runs before the fetch: a file this source
    # cannot publish aborts the run without a network call at all.
    committed = committed_record(root, PRODUCT_ID_IOS, "Cisco IOS")
    checked = _now()
    _, hub_page = _page(IOS_HUB_URL)
    _, catalog_page = _page(IOS_CATALOG_URL)
    trains, hub_rows, catalog_rows, excluded, duplicates = ios_inventory(hub_page, catalog_page)
    releases = []
    for train in trains:
        where = f"Cisco IOS {train['id']} ({train['url']})"
        try:
            final_url, page = _page(train["url"])
        except Exception as error:
            if getattr(getattr(error, "response", None), "status_code", None) != 404:
                raise
            excluded.append({"id": train["id"], "name": train["name"], "listing": train["listing"],
                             "url": train["url"],
                             "reason": "the vendor serves no lifecycle page at this URL "
                                       "(HTTP 404): the train is inventoried by a listing but "
                                       "states no lifecycle of its own here"})
            continue
        if "birth-cert-table" not in page and "Retirement Notification" not in page:
            if final_url == train["url"]:
                raise ValueError(f"{where}: page states no lifecycle table and did not redirect")
            excluded.append({"id": train["id"], "name": train["name"], "listing": train["listing"],
                             "url": train["url"], "final_url": final_url,
                             "reason": "the vendor serves no train-level lifecycle page at this "
                                       "URL; it resolves to the generic IOS/NX-OS software "
                                       "category page, which states no train lifecycle"})
            continue
        title, cells, statement, _ = parse_series(page, where)
        releases.append(page_release(train, title, cells, statement, final_url))
    if not releases:
        raise ValueError("The Cisco IOS listings produced no trains")
    releases, kept = combine_releases(releases, committed, "Cisco IOS")
    record = _record(PRODUCT_ID_IOS, "Cisco IOS",
                     {"ga": SERIES_DATE, "eos": SALE_DATE, "eol": SUPPORT_DATE},
                     releases, IOS_HUB_URL, checked)
    report = ios_report_for(releases, excluded, kept, hub_rows, catalog_rows, duplicates, checked)
    publish_record(record, report, root, IOS_REPORT)
    return (f"imported {len(releases)} Cisco IOS trains "
            f"({len(excluded)} excluded, {len(kept)} retained) (data/{IOS_REPORT})")


def import_nx_os(directory=None):
    """Fetch the NX-OS lifecycle statement and publish the ``cisco-nx-os`` record."""
    root = Path(directory) if directory is not None else ROOT / "data"
    committed = committed_record(root, PRODUCT_ID_NX_OS, "Cisco NX-OS")
    checked = _now()
    _, page = _page(NX_OS_URL)
    tables = _table_blocks(page)
    releases, excluded = parse_lifecycle_page(page)
    releases, kept = combine_releases(releases, committed, "Cisco NX-OS")
    record = _record(PRODUCT_ID_NX_OS, "Cisco NX-OS",
                     {"eossec": SECURITY_LABEL + "/LDoS", "eol": SECURITY_LABEL + "/LDoS"},
                     releases, NX_OS_URL, checked)
    report = nx_os_report_for(releases, excluded, kept, tables, checked)
    publish_record(record, report, root, NX_OS_REPORT)
    return (f"imported {len(releases)} Cisco NX-OS trains "
            f"({len(excluded)} excluded, {len(kept)} retained) (data/{NX_OS_REPORT})")


VALIDATORS = {PRODUCT_ID_IOS: validate_ios_record, PRODUCT_ID_NX_OS: validate_nx_os_record}
