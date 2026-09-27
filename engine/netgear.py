"""NETGEAR product end-of-service, from the vendor's own rendered EoS page (#151, #154).

Source: ``https://www.netgear.com/about/eos/``, NETGEAR's End of Service
Products page, read through the opt-in rendering profile in ``engine.render``
because the product list is assembled client-side. The server HTML is ~480 KB of
application shell with no dates and no table cells; the rendered page carries 68
category tables and 9,405 SKU rows. The plain client cannot read this page at
all, and the evidence for that is in ``contributions/netgear-eos-no-go.md``.

**The column mapping rests on each row's own sentence, not on the columns.** The
rendered page states no column names anywhere — no caption, no header row, no
``data-title``, no ``aria-label`` — and each row is five bare cells: a model, an
item number, a date, a second date, and a note. The note is the vendor's own
unambiguous statement:

* ``The product reached EOS on 09-DEC-2013.`` — the product has reached the end
  of its service.
* ``The product is scheduled to reach EOS on ...`` — the end is announced.
* ``The product you searched has not yet reached the Last Sale Date and therefore
  has at least three years remaining for functional and cyber security updates.``
  — the product has not, and the vendor states no date.

So ``eol`` is the date in the row's note, which is ``DD-MMM-YYYY`` and therefore
unambiguous. The two date cells are **not** read for the milestone, because their
order is ambiguous (``9/12/2013`` is either 9 December or 12 September) and
because the page never says what they are called. They are retained verbatim and
the collector checks each against the note's own day and month, accepting either
order and refusing a cell that reconciles with neither.

**What "EOS" means, in the vendor's words.** "The end of NETGEAR's product
lifecycle is called End of Service or EOS. Products that reach EOS no longer
receive firmware updates, including important security updates." That is terminal
support end, so it fills ``eol`` and not ``eossec``: the vendor states one
terminal date and no separate security window.

**One record per item number, not per model.** The page's own policy says it:
"Note the last sale date may be limited to a particular SKU in an identified
country or region." The data agrees — 783 of 1,273 dated models have item numbers
that disagree on the end of service date, and WNAP210 alone carries eight
different ones. A per-model record would have to drop the minority dates or
invent one, so the item number is the unit the vendor actually dates.

**The one thing this collector does not map.** The earlier of the two date cells
looks like a last-sale date, and in 767 rows it is some years before the end of
service. The page states no column name, so calling it ``eos`` would be inventing
a label the vendor never wrote. It is published verbatim under
``upstream.cells`` with that stated, and the report names the count.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from . import net, render, sources, tables
from .hardware import publish_records, slugify, status_from

SOURCE = sources.source("import-netgear")
VERIFIER = SOURCE.verifier
REPORT = SOURCE.report
SOURCE_URL = SOURCE.url
RECORD_SCHEMA = "https://zarguell.github.io/eoltracker/v1/schema/hardware.json"
VENDOR = "NETGEAR"
CATEGORY_COLUMNS = 5

# The vendor's own statements, required verbatim before any date is read. The
# policy sentence is what makes EOS a terminal support end rather than a sale.
POLICY_TERMINAL_QUOTE = ("Products that reach EOS no longer receive firmware updates, including "
                         "important security updates")
POLICY_SKU_QUOTE = ("Note the last sale date may be limited to a particular SKU in an identified "
                    "country or region")
# The three notes a row can carry, in the vendor's own wording.
REACHED = "The product reached EOS on"
SCHEDULED = "The product is scheduled to reach EOS on"
NOT_YET = "The product you searched has not yet reached the Last Sale Date"
# ``09-DEC-2013`` — unambiguous where the date cells are not.
ROW_DATE = re.compile(r"(?:reached|scheduled to reach) EOS on (?P<day>\d{2})-(?P<month>[A-Z]{3})-"
                      r"(?P<year>\d{4})")
MONTHS = {name: index for index, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
# A date cell: month/day or day/month in a two-digit form, and a four-digit year.
CELL_DATE = re.compile(r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<year>\d{4})\Z")
NO_DATE = frozenset({"", "-", "n/a", "tbd"})


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cell_date(text, where):
    """A date cell as the two numbers it prints, or ``None``.

    The cell's own order is ambiguous — ``9/12/2013`` is 9 December on one row
    and 12 September on another — so a cell is never resolved on its own. It is
    checked against the row's note instead, by :func:`reconciles`.
    """
    value = tables.fold(text)
    if value.lower() in NO_DATE:
        return None
    match = CELL_DATE.fullmatch(value)
    if not match:
        raise ValueError(f"{where}: {value!r} is not a date this page states")
    return int(match.group("a")), int(match.group("b")), int(match.group("year"))


def reconciles(cell, day, month, year):
    """Whether a date cell states the same day as the row's own note.

    Accepting either order is what resolves the cell's ambiguity, and it is a
    real check rather than a formality: the end-of-service cell reconciles with
    the note on every dated row the page states, so a cell that reconciles with
    neither order means the page changed in a way this collector does not
    understand, and the row refuses.
    """
    if cell is None:
        return None
    first, second, cell_year = cell
    if cell_year != year:
        return False
    return (first, second) == (month, day) or (second, first) == (month, day)


def _quoted(html):
    """The rendered page's text with the whitespace of the markup collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def require_policy(html, where):
    """Refuse unless the page still states what EOS means and why dates are per SKU."""
    text = _quoted(html)
    for quote in (POLICY_TERMINAL_QUOTE, POLICY_SKU_QUOTE, NOT_YET):
        if quote not in text:
            raise ValueError(f"{where}: the page no longer states {quote!r}")


def parse(html, where="NETGEAR End of Service Products"):
    """The rendered page as ``(records, accounting)``.

    The page is a flat sequence of 68 single-cell category headers, each followed
    by one five-cell data table. The pairing is read positionally and every
    category name is kept, so a page that grew or lost a category changes the
    count and refuses rather than publishing a shorter inventory.
    """
    require_policy(html, where)
    doc = tables.parse_document(html)
    # The page is a strict alternation: a category heading, then the product
    # table under it, then the next category. Requiring the alternation is what
    # stops a stray one-cell table from being read as a category name, and it
    # guarantees every product table is attributed to a stated category.
    sequence, controls = [], []
    for index, block in enumerate(doc.blocks):
        widths = {len(row) for row in block["rows"]}
        cells = [tables.fold(cell.get("text")) for row in block["rows"] for cell in row]
        if not cells:
            continue
        if index % 2 == 0:
            if widths != {1} or not all(cells):
                controls.extend(cells)
            sequence.append(("category", cells[0] if len(cells) == 1 else None))
        else:
            if widths != {CATEGORY_COLUMNS}:
                controls.extend(cells)
                sequence.append(("table", None))
            else:
                sequence.append(("table", [list(row) for row in block["rows"]]))
    if controls:
        raise ValueError(f"{where}: the page states {len(controls)} block(s) that break the "
                         f"category-then-table alternation, so it is not the page this collector "
                         f"reads")
    categories = [value for kind, value in sequence if kind == "category" and value]
    models = []
    for index in range(len(sequence) - 1):
        kind, value = sequence[index]
        if kind != "category" or not value:
            continue
        following = sequence[index + 1][1]
        if following:
            models.append((value, following))
    if not models:
        raise ValueError(f"{where}: the rendered page states no product table; if the vendor's "
                         f"scripts have changed, this is a page this collector cannot read")
    if len(categories) * 2 != len(sequence) + len(sequence) % 2 and len(models) != len(categories):
        raise ValueError(f"{where}: the page states {len(categories)} categories and "
                         f"{len(models)} product tables; they alternate one for one")

    records, duplicates = [], []
    seen = {}
    for category, rows in models:
        for index, row in enumerate(rows, 1):
            at = f"{where} {category} row {index}"
            cells = [tables.fold(cell.get("text")) for cell in row]
            model, item, first, second, note = cells
            if not item:
                raise ValueError(f"{at}: row states no item number")
            match = ROW_DATE.search(note)
            eol = None
            cells_note = {"model": model, "item number": item, "date 1": first, "date 2": second,
                          "note": note}
            if match:
                day, month_name, year = (int(match.group("day")), match.group("month"),
                                         int(match.group("year")))
                month = MONTHS.get(month_name)
                if month is None:
                    raise ValueError(f"{at}: {month_name!r} is not a month name this page states")
                eol = f"{year:04d}-{month:02d}-{day:02d}"
                # The note decides the date. The second date cell is the one the
                # page puts beside it and is verified against the note on every
                # dated row; the first is a separate date the page never names,
                # so it is checked only for being a date and mapped to nothing.
                for label, cell in (("date 1", first), ("date 2", second)):
                    parsed = cell_date(cell, f"{at} {label}")
                    if label == "date 2" and not reconciles(parsed, day, month, year):
                        raise ValueError(f"{at}: {cell!r} does not state the end-of-service date "
                                         f"the row's own note gives ({eol}); a cell that "
                                         f"reconciles in neither order means the page changed")
                if cell_date(first, at) and cell_date(first, at) != cell_date(second, at):
                    earlier = True
                else:
                    earlier = False
                state = SCHEDULED if note.startswith(SCHEDULED) else REACHED
            elif NOT_YET in note:
                state = NOT_YET
            else:
                raise ValueError(f"{at}: the row's note states no end-of-service sentence: "
                                 f"{note[:80]!r}")
            cells_note["note"] = note
            if match and earlier:
                # Only set when true: a key that is present and says "no" is
                # still a truthy string, and it would count every dated row.
                cells_note["first date differs"] = "yes"
            identity = _identity(model, item)
            if identity in seen:
                if seen[identity] != eol:
                    raise ValueError(f"{at}: item {item} is stated twice with different end-of-"
                                     f"service dates: {seen[identity]} then {eol}")
                duplicates.append({"category": category, "item_number": item,
                                   "reason": "this item number is stated twice in the page under "
                                             "two categories with the same end-of-service date; it "
                                             "is one product, and the second statement is "
                                             "accounted here"})
                continue
            seen[identity] = eol
            records.append(_record(category, model, item, eol, cells_note, identity, where))
    if not records:
        raise ValueError(f"{where}: the page states {len(models)} tables but no item number")
    return records, {
        "categories": len(categories), "tables": len(models),
        "rows": sum(len(rows) for _category, rows in models),
        "published": len(records), "duplicates": duplicates,
        "with_eol": sum(1 for record in records if record["milestones"]["eol"]),
        "not_yet": sum(1 for record in records
                       if (record["upstream"]["Note"]["text"] or "").startswith(NOT_YET)),
        "scheduled": sum(1 for record in records
                         if (record["upstream"]["Note"]["text"] or "").startswith(SCHEDULED)),
        "earlier_date": sum(1 for record in records
                            if record["upstream"]["Date 1"].get("differs from the end of service")
                            == "yes"),
    }


def _identity(model, item):
    """One record id per item number, in the catalog's id grammar."""
    base = slugify(item) or slugify(model)
    if not base:
        raise ValueError(f"Item number {item!r} and model {model!r} state no id characters the "
                         f"catalog allows")
    return f"netgear-{base}"


def _cell(text, note=None):
    """One upstream cell in the shape every hardware collector publishes."""
    cell = {"text": text or None, "value": None, "datetime": None, "role": None, "links": []}
    if note:
        cell["note"] = note
    return cell


def _record(category, model, item, eol, cells, identity, where):
    # Every upstream value is a cell, because that is the shape the published
    # pages and the site read; the category travels as its own cell rather than
    # as a container key, so a reader sees which table each row came from.
    upstream = {
        "Category": _cell(category, "the page's own category heading for this row"),
        "Model": _cell(model),
        "Item Number": _cell(item, "the SKU this record dates; the page states its end of service "
                                    "may be limited to a particular SKU in a particular region"),
        "Date 1": _cell(cells["date 1"],
                        "a date the page states beside the end of service without naming the "
                        "column. It equals the end-of-service date on most rows and is years "
                        "earlier on the rest. It is published verbatim and mapped to nothing, "
                        "because giving it a milestone would be inventing a column name the "
                        "vendor never wrote."),
        "Date 2": _cell(cells["date 2"],
                        "the cell the page prints beside the row's own end-of-service sentence, "
                        "and the one verified against it on every dated row"),
        "Note": _cell(cells["note"], "the row's own statement, and the source of the published "
                                     "end-of-service date"),
    }
    if cells.get("first date differs"):
        upstream["Date 1"]["differs from the end of service"] = "yes"
    return {
        "$schema": RECORD_SCHEMA,
        "id": identity,
        "name": f"NETGEAR {model} ({item})" if model != item else f"NETGEAR {item}",
        "category": "hardware",
        "vendor": VENDOR,
        "product_line": category,
        "family": category,
        "model_number": item,
        "milestones": {"ga": None, "eos": None, "eossec": None, "eol": eol},
        # A row whose own note says the product has not yet reached the end of
        # service is one the vendor calls supported, in those words, so its
        # status is stated rather than derived as "unknown" from a null date.
        "status": "supported" if cells["note"].startswith(NOT_YET) else status_from(eol, _now()),
        "upstream": upstream,
        # The fetch marker is nested, not spread: a reader (and the schema) must
        # see that these three fields describe how the page was read, not that
        # they are fields of provenance in their own right.
        "provenance": {"source_urls": [SOURCE_URL], "verifier": VERIFIER,
                       "last_checked": None, "fetch": render.fetch_note()},
    }


def import_netgear(directory=None):
    """Render the vendor's EoS page and publish one record per item number."""
    root = Path(directory) if directory is not None else Path(__file__).resolve().parents[1] / "data"
    checked = _now()
    rendered = render.render(SOURCE_URL, SOURCE.id)
    records, accounting = parse(rendered.html)
    for record in records:
        if record["upstream"]["Note"]["text"].startswith(NOT_YET):
            record["status"] = "supported"
        else:
            record["status"] = status_from(record["milestones"]["eol"], checked)
        record["provenance"]["last_checked"] = checked
    identities = [record["id"] for record in records]
    if len(set(identities)) != len(identities):
        raise ValueError("Two NETGEAR item numbers publish as one record")
    report = {
        "source_url": SOURCE_URL, "verifier": VERIFIER, "checked_at": checked,
        "fetch_profile": render.PROFILE, "operator_switch": render.switch_state(),
        "record_scope": ("NETGEAR products on the vendor's own End of Service page: one hardware "
                         "record per item number, at the day precision the row's own note states"),
        "rows": {"seen": accounting["rows"], "published": accounting["published"],
                 "with_eol": accounting["with_eol"], "not_yet_eos": accounting["not_yet"],
                 "scheduled": accounting["scheduled"],
                 "duplicates": len(accounting["duplicates"]),
                 "earlier_unnamed_date": accounting["earlier_date"]},
        "categories": accounting["categories"], "tables": accounting["tables"],
        "duplicates": accounting["duplicates"],
        "total_records": len(records),
        "limitations": [
            "The page is read through the opt-in rendering profile because the product list is "
            "assembled client-side: the server HTML is roughly 480 KB of application shell with no "
            "dates and no table cells. A record from this source carries fetch='rendered' in its "
            "provenance, permanently.",
            "The page states no column names anywhere - no caption, no header row, no data-title "
            "and no aria-label - and each row is five bare cells. eol is therefore the date in the "
            "row's own note, which is DD-MMM-YYYY and unambiguous, not either date cell.",
            "The two date cells are retained verbatim and the second is verified against the "
            "row's note on every dated row, accepting either order, because the cells' own order "
            "is ambiguous: 9/12/2013 is 9 December on one row and 12 September on another. A "
            "second cell that reconciles with the note in neither order refuses the row.",
            "The first of the two date cells is a separate, unnamed date: it equals the end of "
            "service on most rows and is years earlier on the rest, and the page states no column "
            "name for it. It looks like a last-sale date and is mapped to nothing rather than "
            "given an eos the vendor never wrote; the count of rows where it differs is in "
            "rows.earlier_unnamed_date.",
            "One record per item number, not per model, because the page's own policy says 'the "
            "last sale date may be limited to a particular SKU in an identified country or region' "
            "and the data agrees: 783 of 1,273 dated models have item numbers that disagree on "
            "the end-of-service date.",
            "A product that has not yet reached the end of service is published with a null eol and "
            "the vendor's own sentence retained, because the page lists it as a current product "
            "and a fleet manager needs to see that it is not yet affected.",
            "EOS is a terminal support end, not a sale or a security-only date: the page states "
            "that products which reach EOS 'no longer receive firmware updates, including important "
            "security updates'. eos and eossec are null everywhere.",
        ],
    }
    publish_records(records, VERIFIER, root, report)
    rows = report["rows"]
    return (f"imported {rows['published']} NETGEAR item numbers from {rows['seen']} rows across "
            f"{accounting['categories']} categories through the {render.PROFILE} profile "
            f"({rows['with_eol']} with an end-of-service date, {rows['not_yet_eos']} not yet, "
            f"{rows['scheduled']} scheduled) (data/{REPORT})")
