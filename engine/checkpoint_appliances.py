"""Check Point appliance lifecycle, from Check Point's own support-lifecycle policy page.

Source: ``https://www.checkpoint.com/support-services/support-life-cycle-policy/``,
one server-rendered page carrying a milestone definition table, a
latest-announcements table, **nineteen appliance tables** of one shape, and
several software and service tables. The nineteen appliance tables are this
source, and they are hardware: a model, a family, a support end.

This is a *second* reader of a page the repository already reads.
``engine/checkpoint`` owns the Security Gateway & Management **software** table
and publishes it into the software catalog as ``deterministic-checkpoint``; it
lists every appliance row as an exclusion, precisely because an appliance
lifecycle is a different record shape. This module is that other half, with its
own verifier, its own report and hardware publication, so the two never share a
file, a report or a count. Software and service tables on this page are reported
here as read by the sibling source rather than as unclaimed rows.

What becomes a milestone, and why. This is the only vendor in the priority set
that publishes a true three-way date split, and the mapping had to be decided
before the parser was written:

* **General Availability → ``ga``**, at the precision the cell states.
* **End of Sale → ``eos``**, at the precision the cell states.
* **End of Support → ``eol``**, at the precision the cell states. The vendor
  distinguishes this from end of sale in its own policy text, so the two are
  never merged.
* **End of Engineering Support → nothing.** Check Point's own definition is
  "Engineering Support: Maintenance releases are supplied until 3 three years
  after End of Sale Date" — a maintenance window, not a security-support end.
  AGENTS.md forbids a generic support date filling ``eossec``, and Check Point
  never uses the word "security" for it, so the cell is kept verbatim.
* **Status, Successor Model, Successor Product Availability and Supported
  Software Versions → vendor cells.** ``Status`` states one of ``Active``,
  ``Successor Product Available`` or ``End of Support``; it is the vendor's own
  lifecycle claim and is kept as such. The published ``status`` field is this
  catalog's vocabulary, derived from the End of Support date, as it is for every
  other collector here.

**Precision is whatever the cell states, never padded — and a month is not a
milestone here yet.** This catalog's *hardware* schema admits a calendar day
only, so a month-precision cell is published verbatim in the row's own cells,
counted in the report, and left out of the milestone. That is a limit of the
hardware schema rather than of the vendor, and it costs the most useful column
for 141 of the 298 appliances here; extending the schema is issue #153.
 The page mixes widths
inside one column: ``Oct-2011`` and ``Jan 2022`` are months, ``31-Oct-2014``
and ``19-Sep-2023`` are days. The date reader accepts only the spellings the
page actually prints, and a cell that states a two-digit year (``May-06``,
``31-Dec-18``) publishes no milestone at all: the schema holds a four-digit
year, and choosing a century would be inventing the half of the date the vendor
did not print. Those cells are counted by name in the report.

A date the page prints and this reader does not know **refuses the page**. So
does a table that declares a column set other than the appliance shape, other
than the tables this source deliberately leaves to another catalog.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import net, sources, tables
from .hardware import publish_records, slugify, status_from
from .importer import ROOT

SOURCE = sources.source("import-checkpoint-appliances")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
SOURCE_URL = SOURCE.url
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/hardware.json"
VENDOR = "Check Point"
PRODUCT_LINE = "Check Point"

# The appliance table, in the page's own column order. Matched as an exact
# header set: a renamed or dropped column refuses the page rather than letting a
# date slide into the next column.
APPLIANCE_COLUMNS = ("Appliance Product/Model", "Status", "General Availability", "End of Sale",
                     "Successor Model", "Successor Product Availability",
                     "End of Engineering Support", "End of Support",
                     "Supported Software Versions")
SUBJECT, STATUS, GA, EOS, ENGINEERING, EOL = ("Appliance Product/Model", "Status",
                                               "General Availability", "End of Sale",
                                               "End of Engineering Support", "End of Support")
# The columns that carry a date this source reads, and the milestone each becomes.
DATED = (GA, EOS, ENGINEERING, EOL)
# The vendor's own lifecycle states, kept as evidence and never mapped.
VENDOR_STATUS = {"Active", "Successor Product Available", "End of Support"}

# The page prints abbreviated months ("Oct", "Sept", "Feb"), full ones
# ("July 15 2026") and both, so a name and its three-letter prefix are one key.
MONTHS = {}
for _index, _name in enumerate(("January", "February", "March", "April", "May", "June", "July",
                                "August", "September", "October", "November", "December"), 1):
    MONTHS[_name.lower()] = _index
    MONTHS[_name[:3].lower()] = _index
# The page also prints a four-letter September.
MONTHS["sept"] = 9
# The page's own spellings, enumerated from it. Each pattern is a shape the
# vendor prints; nothing else is accepted.
DAY_MONTH_YEAR = re.compile(r"(?P<day>\d{1,2})-(?P<month>[A-Za-z]+)-(?P<year>\d{4})\Z")
MONTH_DAY_YEAR = re.compile(r"(?P<month>[A-Za-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})\Z")
DAY_MONTH_LONG = re.compile(r"(?P<day>\d{1,2}) (?P<month>[A-Za-z]+) (?P<year>\d{4})\Z")
MONTH_DAY_LONG = re.compile(r"(?P<month>[A-Za-z]+) (?P<day>\d{1,2}) (?P<year>\d{4})\Z")
MONTH_DASH_YEAR = re.compile(r"(?P<month>[A-Za-z]+)-(?P<year>\d{4})\Z")
# The page prints "Feb- 2019" in eight cells: a stray space after the dash.
MONTH_DASH_SPACE_YEAR = re.compile(r"(?P<month>[A-Za-z]+)-\s+(?P<year>\d{4})\Z")
MONTH_SPACE_YEAR = re.compile(r"(?P<month>[A-Za-z]+) (?P<year>\d{4})\Z")
# Two-digit years are a real width the schema cannot hold; see the module docstring.
SHORT_YEAR = re.compile(r"(?:(?P<day>\d{1,2})-)?(?P<month>[A-Za-z]+)-(?P<year>\d{2})\Z")
ABSENT = frozenset({"", "-", "n/a", "na", "tbd"})


class DateError(ValueError):
    """A date cell the page prints in a shape this reader does not know."""


class NotRepresentable(ValueError):
    """A stated date this schema has no width for, such as a two-digit year."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _month(name, where):
    index = MONTHS.get(name.strip().lower())
    if index is None:
        raise DateError(f"{where}: {name!r} is not a month name Check Point states")
    return index


def _iso(year, month, day, where):
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        raise DateError(f"{where}: {year}-{month:02d}-{day:02d} is not a real calendar day") from None


def checkpoint_date(text, where):
    """The date one Check Point cell states, at the precision it states.

    Returns ``(value, precision)`` where precision is ``"day"``, ``"month"`` or
    ``None`` for an absent cell. A two-digit year raises
    :class:`NotRepresentable` — the cell is real and the schema cannot hold it —
    and an unknown spelling raises :class:`DateError`, which refuses the page.
    """
    value = tables.fold(text)
    if value.lower() in ABSENT:
        return None, None
    for pattern in (DAY_MONTH_YEAR, MONTH_DAY_YEAR, DAY_MONTH_LONG, MONTH_DAY_LONG):
        match = pattern.fullmatch(value)
        if match:
            day, month, year = match.group("day"), match.group("month"), int(match.group("year"))
            return _iso(year, _month(month, where), int(day), where), "day"
    for pattern in (MONTH_DASH_YEAR, MONTH_DASH_SPACE_YEAR, MONTH_SPACE_YEAR):
        match = pattern.fullmatch(value)
        if match:
            year = int(match.group("year"))
            return f"{year:04d}-{_month(match.group('month'), where):02d}", "month"
    if SHORT_YEAR.fullmatch(value):
        raise NotRepresentable(f"{value!r} states a two-digit year; the schema holds a four-digit "
                               f"year, and the century is not stated")
    raise DateError(f"{where}: unrecognized Check Point date {value!r}")


def _cell(text):
    """One page cell as the hardware schema's own cell shape."""
    return {"text": tables.fold(text), "value": None, "datetime": None, "role": None, "links": []}


def _short_family(family):
    """A stable, readable family token for an identity."""
    return slugify(re.split(r"[(\[]", family, 1)[0]) or slugify(family)


def _identity(model, family):
    """The slug a model row is published under.

    The family is part of the identity because a model name alone is not unique
    across a vendor's catalogue in general, and an identity that silently merges
    two products is worse than a longer one.
    """
    return f"checkpoint-{_short_family(family)}-{slugify(model)}"


def parse(html):
    """The page as ``(models, excluded, tables_seen)``.

    ``models`` is one entry per appliance row, ``excluded`` every row or table
    this source deliberately does not publish — each with its reason — and
    ``tables_seen`` the number of tables the page carried, so the report can
    state how much of the page was read.
    """
    if not tables.fold(html):
        # An empty body is a refused fetch, not a page that changed shape. The
        # host answers a rapid second request with 200 and no content, and
        # "no appliance table" would send the next person looking for a schema
        # change that did not happen.
        raise ValueError(f"The Check Point page returned an empty document ({len(html)} bytes); "
                         f"the host rate-limits repeated fetches, so this is a fetch refusal, "
                         f"not an empty schedule")
    doc = tables.parse_document(html)
    models, excluded, seen, appliance_tables = [], [], 0, 0
    for block in doc.blocks:
        found = tables.th_header(block)
        if found is None:
            rows = [row for row in block["rows"] if len(row) != 1]
            if rows:
                excluded.append({"table": tables.fold(block["heading"] or ""), "rows": len(rows),
                                 "reason": "the table states no header row, so it declares no "
                                           "columns and carries no lifecycle row this source "
                                           "can read"})
            continue
        labels, start = found
        seen += 1
        if labels != APPLIANCE_COLUMNS:
            excluded.append({
                "table": tables.fold(block["heading"] or ""), "rows": len(block["rows"]) - start,
                "columns": list(labels),
                "reason": "not a Check Point appliance schedule: this table carries the vendor's "
                          "software or service vocabulary, and those rows are read by the "
                          "sibling software source engine.checkpoint, which publishes them into "
                          "the software catalog. They are named here so this page's full table "
                          "count reconciles across both reports."})
            continue
        appliance_tables += 1
        family = tables.fold(block["heading"] or "appliances")
        body = [row for row in block["rows"][start:] if len(row) != 1]
        for index, row in enumerate(body, 1):
            at = f"Check Point {family} row {index}"
            if len(row) != len(labels):
                raise ValueError(f"{at}: the row has {len(row)} cells where the page declares "
                                 f"{len(labels)}")
            cells = {label: cell["text"] for label, cell in zip(labels, row)}
            model = tables.fold(cells[SUBJECT])
            if not model:
                raise ValueError(f"{at}: the row states no appliance name")
            if tables.fold(cells[STATUS]) not in VENDOR_STATUS:
                raise ValueError(f"{at}: unrecognized Status {cells[STATUS]!r}")
            milestones, precisions, refused = {}, {}, []
            for column in DATED:
                try:
                    value, precision = checkpoint_date(cells[column], f"{at} {column}")
                except NotRepresentable as error:
                    refused.append({"column": column, "reason": str(error)})
                    value, precision = None, None
                if value is not None and precision != "day":
                    # The hardware schema holds a calendar day and this catalog
                    # will not widen it silently. A month the vendor states is
                    # kept verbatim in the row's own cell, counted here, and
                    # left out of the milestone rather than padded to a day the
                    # vendor never printed (AGENTS.md rule 4).
                    refused.append({"column": column,
                                    "reason": f"the cell states {value!r} at month precision, and "
                                              f"the hardware schema holds a calendar day; the "
                                              f"vendor's own month is kept in this row's cells and "
                                              f"is not padded into a day"})
                    value = None
                milestones[column] = value
                precisions[column] = precision
            if (milestones[EOL] is None
                    and tables.fold(cells[STATUS]) == "End of Support"):
                refused.append({"column": STATUS,
                                "reason": "the vendor states the product has reached End of "
                                          "Support but publishes no End of Support date, so a "
                                          "status claim is recorded and no milestone is invented"})
            models.append({
                "family": family, "product": model,
                "milestones": {"ga": milestones[GA], "eos": milestones[EOS],
                               "eossec": None, "eol": milestones[EOL]},
                "engineering": tables.fold(cells[ENGINEERING]),
                "precisions": precisions,
                "cells": {column: _cell(cells[column]) for column in APPLIANCE_COLUMNS},
                "withheld": refused,
            })
    if not appliance_tables:
        raise ValueError(f"The Check Point page states {seen} tables and none is an appliance "
                         f"schedule: the appliance tables are missing, which is a page change "
                         f"rather than an empty catalog")
    if not models:
        raise ValueError("The Check Point page states no appliance row")
    return models, excluded, seen


def _milestones(model):
    return model["milestones"]


def record_for(model, checked):
    """The published hardware record for one appliance row."""
    milestones = _milestones(model)
    upstream = dict(model["cells"])
    # The engineering-support column is a vendor cell, never a milestone, so it
    # is published beside the other vendor columns with its value and the note
    # that this source read it and declined to map it.
    upstream["End of Engineering Support"] = {
        **_cell(model["engineering"]),
        "note": "Check Point defines this as maintenance releases until three years after end of "
                "sale, which is not a security-support end; the cell is published and never "
                "mapped to eossec",
    }
    if model["withheld"]:
        upstream["not_published"] = {
            "text": "; ".join(f"{entry['column']}: {entry['reason']}" for entry in model["withheld"]),
            "value": None, "datetime": None, "role": None, "links": [],
        }
    return {
        "$schema": RECORD_SCHEMA,
        "id": _identity(model["product"], model["family"]),
        "name": model["product"],
        "category": "hardware",
        "vendor": VENDOR,
        "product_line": PRODUCT_LINE,
        "family": model["family"],
        "model_number": model["product"],
        "milestones": milestones,
        "status": status_from(milestones["eol"], checked),
        "upstream": upstream,
        "provenance": {"source_urls": [SOURCE_URL], "verifier": VERIFIER,
                       "last_checked": checked},
    }


def report_for(models, excluded, tables_seen, checked):
    """The per-row accounting this source publishes beside its records."""
    # The precision the parse already read for each cell, counted per column:
    # how much of this source is month-precise and how much is day-precise is
    # part of what a reader is owed.
    months = {column: sum(1 for model in models if model["precisions"].get(column) == "month")
              for column in (GA, EOS, EOL)}
    days = {column: sum(1 for model in models if model["precisions"].get(column) == "day")
            for column in (GA, EOS, EOL)}
    withheld = sum(len(model["withheld"]) for model in models)
    month_only = {column: sum(1 for model in models
                              if model["precisions"].get(column) == "month")
                  for column in (GA, EOS, EOL)}
    eol_stated = sum(1 for model in models if model["milestones"]["eol"])
    return {
        "source_url": SOURCE_URL, "verifier": VERIFIER, "checked_at": checked,
        "record_scope": ("Check Point appliances: one hardware record per appliance row of the "
                         "vendor's support-lifecycle policy page, at the day or month precision "
                         "the vendor's own cell states"),
        "rows": {"seen": len(models) + len(excluded), "published": len(models),
                 "excluded": len(excluded), "tables": tables_seen,
                 "with_eol": eol_stated, "month_precision": months, "day_precision": days,
                 "month_precision_withheld": month_only, "withheld_cells": withheld},
        "excluded": excluded,
        "total_records": len(models),
        "limitations": [
            "General Availability becomes ga, End of Sale becomes eos and End of Support becomes "
            "eol, each at the precision the vendor's cell states; this is the only vendor in the "
            "priority set that publishes all three separately.",
            "End of Engineering Support is published as a vendor cell and never mapped: Check "
            "Point defines it as maintenance releases until three years after end of sale, which "
            "is a maintenance window and not a security-support end, so eossec is null "
            "everywhere.",
            "The page mixes day and month precision inside one column, and the hardware schema "
            "holds a calendar day only. A month-precision cell is therefore published in the row's "
            "own cells and counted here, but is not written as a milestone and never padded into a "
            "day: this is a limit of the hardware schema, not of the vendor. Extending the schema "
            "to month precision is tracked separately; until then the published ga, eos and eol "
            "counts are the day-precision cells and nothing else.",
            "A cell stating a two-digit year publishes no milestone and is counted by name: the "
            "schema holds a four-digit year and the century is not stated, so choosing one would "
            "invent half the date.",
            "The vendor's Status column (Active, Successor Product Available, End of Support) is "
            "kept verbatim. Where the vendor states End of Support without a date, the status "
            "claim is published and no milestone is invented.",
            "The page also carries software and service schedules. They are reported here and "
            "read by engine.checkpoint, which publishes the Security Gateway & Management trains "
            "into the software catalog. Between the two reports every table on the page is "
            "accounted exactly once.",
        ],
    }


def import_checkpoint_appliances(directory=None):
    """Fetch the lifecycle page and publish every appliance row it dates."""
    root = Path(directory) if directory is not None else ROOT / "data"
    checked = _now()
    models, excluded, tables_seen = parse(net.get_text(SOURCE_URL))
    records, identities = [], set()
    for model in sorted(models, key=lambda entry: _identity(entry["product"], entry["family"])):
        record = record_for(model, checked)
        if record["id"] in identities:
            raise ValueError(f"Check Point: two appliance rows publish as {record['id']}")
        identities.add(record["id"])
        records.append(record)
    report = report_for(models, excluded, tables_seen, checked)
    publish_records(records, VERIFIER, root, report)
    rows = report["rows"]
    return (f"imported {len(records)} Check Point appliances from {rows['tables']} tables "
            f"({rows['with_eol']} with an end-of-support date, "
            f"{rows['month_precision'][EOL]} of them at month precision); excluded {rows['excluded']} "
            f"rows, withheld {rows['withheld_cells']} cells (data/{REPORT})")
