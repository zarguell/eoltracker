"""Read a vendor's HTML lifecycle tables without guessing at their shape.

One parser serves every vendor collector that reads tables out of static HTML:
Progress's Zoomin and Sitefinity pages, SolarWinds' MadCap release histories,
and any other page that states its rows in real ``<table>`` markup. The parser
records structure only — it decides nothing about what a column means, which
each collector's own reviewed table specification does.

A page is read as:

* ``blocks`` — every ``<table>`` in document order, each attached to the
  heading in force and keeping its ``class``, so a table is found by the
  vendor's own section name rather than by its position on the page;
* ``headings`` / ``page_text`` — the section names, and the whole page's
  flattened text, which a collector requires verbatim before it will read a
  rule or a footnote out of a page;
* each table's ``rows``, a list of cells carrying their text, the text of
  their first block (``lead``), whether they are a ``<th>`` or a ``<td>``, and
  their declared ``rowspan``/``colspan``.

Nothing here is fail-closed by itself: the readers below refuse a table whose
shape a collector's specification does not describe, but which shape is a
problem is the collector's decision, because two vendors need two different
refusals.
"""
from __future__ import annotations

from html.parser import HTMLParser


def fold(text):
    """Cell or heading text with non-breaking spaces resolved and whitespace folded."""
    return " ".join((text or "").replace("\xa0", " ").split())


def lines(text):
    """A cell's own lines, each folded — the page's ``<br>`` group separator."""
    return [line for line in (fold(part) for part in (text or "").replace("\xa0", " ").split("\n"))
            if line]


class Document(HTMLParser):
    """One vendor page as headings, tables, and its whole flattened text.

    Cells keep their declared ``rowspan``/``colspan``; a caller that states one
    cell per column refuses a spanned data cell itself. ``<br>`` becomes a
    newline because vendors use it to bundle several values into one cell.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.text = []
        self.headings = []
        self.heading = None
        self.page_text = ""
        self._heading = None
        self._table = None
        self._row = None
        self._cell = None
        self._lead = None
        self._attrs = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = []
        elif tag == "table":
            if self._table is not None:
                raise ValueError("nested table in a vendor page")
            self._table = {"heading": self.heading, "rows": [],
                           "class": dict(attrs).get("class", "")}
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            # ``lead`` is the cell's first block of text: the product name a
            # cell states before the list of documentation links that follows
            # it, or the label a header cell states before its own note. A
            # cell with no nested block has a lead equal to its whole text.
            self._lead = []
            self._lead_frozen = None
            self._attrs = dict(attrs)
        elif self._cell is None:
            return
        elif tag == "p" and self._lead is not None and "".join(self._lead).strip():
            self._freeze_lead()
        elif tag not in ("b", "i", "u", "span", "em", "strong", "a", "code", "img", "p"):
            self._freeze_lead()

    def _freeze_lead(self):
        """End the cell's first block, keeping the text it stated so far."""
        if self._lead is not None:
            self._lead_frozen = "".join(self._lead)
            self._lead = None

    def handle_data(self, data):
        if self._skip:
            return
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)
            if self._lead is not None:
                self._lead.append(data)
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading is not None:
            self.heading = fold("".join(self._heading))
            self.headings.append(self.heading)
            self._heading = None
        elif tag in ("td", "th") and self._cell is not None:
            attrs = self._attrs or {}
            lead = self._lead_frozen if self._lead_frozen is not None else "".join(self._lead or [])
            self._row.append({"text": "".join(self._cell).strip(),
                              "lead": fold(lead),
                              "th": tag == "th",
                              "span": (int(attrs.get("rowspan", "1") or 1),
                                       int(attrs.get("colspan", "1") or 1))})
            self._cell = None
            self._lead = None
            self._lead_frozen = None
            self._attrs = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.blocks.append(self._table)
            self._table = None

    def close(self):
        super().close()
        self.page_text = fold("".join(self.text))


def parse_document(html):
    """One vendor page as a :class:`Document`."""
    doc = Document()
    doc.feed(html)
    doc.close()
    return doc


def heading_table(doc, heading, where):
    """The one table the page states under ``heading``."""
    found = [block for block in doc.blocks if block["heading"] == fold(heading)]
    if len(found) != 1:
        raise ValueError(f"{where}: expected exactly one {fold(heading)!r} table, found {len(found)}")
    return found[0]


def header_rows(block, where):
    """The vendor header rows of a table, and where its data rows begin.

    A declared table header is a leading run of rows whose every cell is a
    ``<th>``. Some vendor tables state their header in the first body row with
    ``<td>`` cells instead, which is accepted only when the table states no
    ``<th>`` at all, so a ``<th>`` appearing anywhere in a ``<td>``-headed table
    refuses instead of silently shifting the header.
    """
    rows = block["rows"]
    if not rows:
        raise ValueError(f"{where}: table is empty")
    index = 0
    while index < len(rows) and all(cell["th"] for cell in rows[index]):
        index += 1
    if index:
        return rows[:index], index
    if any(cell["th"] for row in rows for cell in row):
        raise ValueError(f"{where}: table mixes <th> and <td> header rows")
    return rows[:1], 1


def th_header(block):
    """The table's first all-``<th>`` row and where its data rows begin.

    Some vendor tables open with a caption or a note row before the header, so
    the header is the first row every one of whose cells is a ``<th>``, wherever
    that appears. Returns ``(headers, start)``, or ``None`` when the table
    states no header at all — a layout table, which a caller either skips or
    refuses, never reads as data.
    """
    for index, row in enumerate(block["rows"]):
        if row and all(cell["th"] for cell in row):
            return tuple(fold(cell["lead"] or cell["text"]) for cell in row), index + 1
    return None


def spanned_rows(block, labels, start):
    """A table's body split into its data rows and its full-width control rows.

    Some schedules end with a one-cell row that spans every column — a
    "show all versions" toggle rather than a schedule row. It is separated here
    instead of being refused as a ragged row, so the caller decides what it is:
    named and accounted for where the page states one, refused where the page
    declares none.
    """
    data, controls = [], []
    for row in block["rows"][start:]:
        if len(row) == 1 and row[0]["span"][1] == len(labels):
            controls.append(fold(row[0]["text"]))
        else:
            data.append(row)
    return data, controls


def data_rows(rows, where, heading, labels):
    """Every data row as a ``{label: cell text}`` mapping; width is exact."""
    parsed = []
    for row in rows:
        if len(row) != len(labels):
            raise ValueError(f"{where}: {heading} row has {len(row)} cells, "
                             f"expected {len(labels)}")
        for cell in row:
            if cell["span"] != (1, 1):
                raise ValueError(f"{where}: {heading} data cell carries span {cell['span']}")
        parsed.append({label: cell["text"] for label, cell in zip(labels, row)})
    return parsed
