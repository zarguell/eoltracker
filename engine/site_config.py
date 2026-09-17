"""Presentation configuration: paths, identity, catalog vocabulary and the Jinja environment.

Nothing here reads the catalog. The module answers the three questions the
templates and the renderers ask constantly — where does this URL live
(`url_for`, `site_url`), how is a value spelled for a reader (`human_date`,
`human_datetime`, `plural`) and which vocabulary does a catalog use
(`MILESTONES` for software, `HARDWARE_MILESTONES` for hardware) — and it wires
those answers into the single Jinja environment every page renders through.

Source identity is deliberately absent: which source published a record, what
that source is called and what its attribution says belong to the source
registry (`engine.sources`), and `engine.site_sources` looks them up. The two
identity facts this module does hold are the ones the registry does not own —
the software source's license, which is a property of the data rather than of
the pipeline that fetched it, and this project's own URLs.

The catalogs' semantics stay out too: this module states what a milestone is
called and what a page prints for it, never what a date means.
"""
import json
import re
from datetime import date, datetime, timezone
from calendar import monthrange
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .importer import ROOT
from . import sources

TEMPLATES = Path(__file__).resolve().parent / "templates"
SCHEMA_DIR = ROOT / "schema"
DEFAULT_DATA = ROOT / "data"
DEFAULT_OUT = ROOT / "_site"

SITE_ORIGIN = "https://zarguell.github.io"
BASE_PATH = "/eoltracker/"
SITE_URL = SITE_ORIGIN + BASE_PATH
SCHEMA_VERSION = "1.0"
REPOSITORY_URL = "https://github.com/zarguell/eoltracker"
# Root notice files republished unchanged alongside the catalog when present.
NOTICE_FILES = ("THIRD-PARTY-NOTICES.txt", "OASIS-NOTICE.txt")

# The two sources the site credits by name. Looked up by the id the CLI and the
# refresh workflow use, so a renamed or added collector reaches the pages
# without a second list here.
SOFTWARE_SOURCE = sources.source("import-data")
EOSL_SOURCE = sources.source("import-hardware")
OPENGEAR_SOURCE = sources.source("import-opengear")
# The verifier ids the registry owns, re-exported under the names the catalog
# code reads, so a committed record's verifier is compared against the registry
# rather than against a string restated in the site layer.
EOSL_VERIFIER = EOSL_SOURCE.verifier
OPENGEAR_VERIFIER = OPENGEAR_SOURCE.verifier
# The software source's license is a fact about the data, not about the fetch,
# so the registry does not carry it; the hardware sources publish none at all
# and are attributed by name and link instead (see the registry's attribution).
SOURCE_LICENSE = "MIT"
SOURCE_LICENSE_URL = "https://github.com/endoflife-date/endoflife.date/blob/master/LICENSE"
# Both vendor pipelines report their catalog partitions here; see
# `site_views.vendor_shards` and the build's `v1/hardware/vendors.json`.
VENDOR_INDEX = "v1/hardware/vendors.json"
CHANGES_ATOM = "v1/changes.atom"
CHANGES_JSON = "v1/changes.json"

# One entry per normalized milestone: the label shown to readers, the upstream
# fields that can feed it, and the conservative rule that decides whether they do.
MILESTONES = (
    {
        "key": "ga",
        "short": "GA",
        "label": "General availability",
        "detail": "First public release. Taken from the upstream releaseDate.",
    },
    {
        "key": "eos",
        "short": "EoS",
        "label": "End of sale",
        "detail": "Last day new licenses or units are sold. Only mapped from an upstream field whose label names an end of sale.",
    },
    {
        "key": "eossec",
        "short": "EoSS",
        "label": "End of security support",
        "detail": "Last day security fixes are published. Mapped from eolFrom or eoesFrom only when the label names security support.",
    },
    {
        "key": "eol",
        "short": "EoL",
        "label": "End of life",
        "detail": "End of all support. A published extended-support date wins; otherwise eolFrom when its label describes a full support end.",
    },
)
MILESTONE_FIELDS = {
    "ga": ("releaseDate",),
    "eos": ("eoasFrom", "discontinuedFrom"),
    "eossec": ("eolFrom", "eoesFrom"),
    "eol": ("eolFrom", "eoesFrom"),
}
# The hardware catalog uses its own vocabulary: eosl.date publishes a release
# date column, an end-of-sales column and a terminal support column, and no
# security-support column at all, so the same four keys carry different rules.
# Keeping them apart means a hardware page never quotes a software mapping rule
# that does not apply to the source it was built from.
HARDWARE_MILESTONES = (
    {
        "key": "ga",
        "short": "GA",
        "label": "General availability",
        "detail": "First availability, when the source publishes a release or launch date. Opengear does not publish GA in its lifecycle tables.",
    },
    {
        "key": "eos",
        "short": "EoS",
        "label": "End of sale",
        "detail": "Last day sold: eosl.date's end-of-life-date column or Opengear's End of Sale / Old Part Sales End.",
    },
    {
        "key": "eossec",
        "short": "EoSS",
        "label": "End of security support",
        "detail": "No separate security-support deadline is normalized from these sources. Opengear contract exceptions remain in raw policy notes.",
    },
    {
        "key": "eol",
        "short": "EoL",
        "label": "End of support",
        "detail": "Published support end: eosl.date's EOSL/LDOS or Opengear's End of Support / Old Part Support Ends. Individual contract exceptions may apply.",
    },
)
MILESTONE_KEYS = tuple(milestone["key"] for milestone in HARDWARE_MILESTONES)
# eosl.date states lifecycle status through the row class of each model row.
# Catalog rows have no status of their own — a current catalogue listing says
# nothing about support — so `unknown` is a first-class, neutral value rather
# than a default. It is deliberately not in HARDWARE_STATUS_ORDER: neutral
# records sort last instead of landing between two dated claims.
HARDWARE_STATUSES = (
    {"key": "supported", "label": "Supported", "detail": "Published in a supported row: no support end has been announced."},
    {"key": "expiring", "label": "Expiring", "detail": "Source warning row, or Opengear's announced support deadline has not yet passed."},
    {"key": "eol", "label": "End of life", "detail": "Source end-of-life row, or Opengear's published support deadline has passed; contract exceptions may apply."},
    {"key": "unknown", "label": "Status unknown", "detail": "No support deadline and no lifecycle notice published for this record, so it carries no support claim in either direction. A current catalogue listing, or a revision-only notice, does not end support."},
)
HARDWARE_STATUS_ORDER = tuple(status["key"] for status in HARDWARE_STATUSES if status["key"] != "unknown")
# ---------------------------------------------------------------------------
# Exact catalogue models (vendor configurator).
#
# These records are not lifecycle rows: each one is one exact vendor model
# string, and it stays that record even after a notice names it. It carries no
# milestone of its own and no support status — the pairs below say only whether
# it is currently listed by the vendor and whether an exact notice for it
# exists right now. Everything here is absent rather than guessed for records
# from other sources.
#
# Which source owns this record shape is the registry's answer, and which page
# it is read from is that source's leading page; the configurator's URL and name
# are therefore never restated here.
# One entry per catalog state: the filter key, its label, and the sentence the
# page prints. `listed` is the catalogue half only — never a support claim.
CATALOG_LISTING_STATES = (
    {"key": "listed", "label": "Listed in vendor catalog",
     "detail": "The vendor configurator currently lists this exact model."},
    {"key": "absent", "label": "Previously listed; absent from latest catalog",
     "detail": "This record was listed when it was first captured and is not in the current catalogue. Absence is not an end-of-sale or end-of-support announcement."},
)
# The notice half. `noticed` needs a published announcement that names this
# exact model; a current listing on its own never sets it.
CATALOG_NOTICE_STATES = (
    {"key": "noticed", "label": "Notice names this exact model",
     "detail": "A published lifecycle notice resolves to this exact model string. The notice's own dates and scope are on the linked record."},
    {"key": "no-notice", "label": "No matching notice",
     "detail": "No published lifecycle notice resolves to this exact model, so no support end is known for it. The vendor lists it; that is not an entitlement."},
)
# One row per possible pair: catalogue listing, then notice state. The filter
# value is the pair, so a reader can ask for exactly the combination they mean.
CATALOG_STATES = tuple(
    {"key": f"{listing['key']}-{notice['key']}", "listing": listing, "notice": notice}
    for listing in CATALOG_LISTING_STATES for notice in CATALOG_NOTICE_STATES
)
# Upstream date fields, in the order they appear in the raw release object, and
# the label field that qualifies each one.
UPSTREAM_DATE_FIELDS = (
    ("releaseDate", None),
    ("eoasFrom", "eoas"),
    ("discontinuedFrom", "discontinued"),
    ("eolFrom", "eol"),
    ("eoesFrom", "eoes"),
)
LABEL_RULES = (
    ("eoas", "End-of-sale date when the text names an end of sale."),
    ("discontinued", "End-of-sale date when the text names an end of sale; otherwise recorded only, never turned into a date."),
    ("eol", "End of security support when the text names security support; end of life only when no extended-support label is set and the text describes a full support end."),
    ("eoes", "Extended support. A published date also sets end of life, and a security-support text supersedes end of security support."),
)

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def tojson_pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


env.filters["tojson_pretty"] = tojson_pretty


def url_for(path=""):
    """Site-root URL for a path inside the published site (GitHub Pages subpath)."""
    return BASE_PATH + str(path).lstrip("/")


def site_url(path=""):
    """Absolute URL for a path inside the published site."""
    return SITE_URL + str(path).lstrip("/")


MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")


def month_value(value):
    """The ``YYYY-MM`` of a month-precision value, else None.

    Month precision is a published shape of its own (AGENTS.md rule 4): a
    source that states "July 2028" states no day, so the value stays a month
    everywhere rather than growing an invented one.
    """
    match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", str(value)) if value else None
    return (int(match.group(1)), int(match.group(2))) if match else None


def is_month(value):
    """True for a month-precision ``YYYY-MM`` value."""
    return month_value(value) is not None


def month_end(value):
    """The last calendar day of a month-precision ``YYYY-MM`` value, else None.

    A month covers every day it contains, so a comparison against "today" has
    to use its own width — the month's end — rather than a day the source never
    stated. `monthrange` also keeps February and leap years honest.
    """
    month = month_value(value)
    if not month:
        return None
    year, number = month
    return date(year, number, monthrange(year, number)[1])


def human_date(value):
    """A reader-facing date: ``Jul 15, 2028``, or ``July 2028`` at month precision.

    The month form states no day because there is none to state — it is the
    whole width of the value, not a truncation of a day that upstream published.
    """
    if not value:
        return None
    month = month_value(value)
    if month:
        year, number = month
        return f"{MONTH_NAMES[number - 1]} {year}"
    parsed = date.fromisoformat(value)
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def published_period(value):
    """The last day a published milestone covers: its day, or a month's own end."""
    return month_end(value) or date.fromisoformat(value)


def source_name_for(verifier):
    """The published name of the registered source behind a record's verifier, else None.

    Read from the registry rather than restated here, so a renamed or added
    collector reaches the pages without a second list. A `researched-*` verifier
    names a contributor, not a pipeline, so it resolves to None and is never
    credited to a source that did not read the record.
    """
    found = sources.sources_for(verifier)
    return found[0].name if found else None


def source_attribution_for(verifier):
    """The credit sentence published for a record's source, or an empty string."""
    found = sources.sources_for(verifier)
    return found[0].attribution if found else ""


def endoflife_date_record(verifier):
    """True when a software record's dates come from the endoflife.date label mapping.

    The label rules and the extended-support legend describe that one pipeline,
    so a vendor collector's own record must not claim them. Read from the
    registry, so a renamed or added software source needs no change here.
    """
    return verifier == SOFTWARE_SOURCE.verifier


def source_link(url):
    """A source page as `{url, label}`, labelled by the registry when it knows it."""
    return {"url": url, "label": sources.source_label(url)} if url else None


def human_datetime(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year} at {parsed.strftime('%H:%M')} UTC"


def human_stamp(value):
    """A readable stamp for a value that may be a date or a date-time.

    Provenance mixes the two — a reading date is a day, a check timestamp is an
    instant — and both are shown to readers, so the width is decided by the
    value rather than by the field it came from.
    """
    if not value:
        return None
    return human_datetime(value) if "T" in str(value) else human_date(str(value))


def plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def version_key(value):
    """Sortable key for release labels: numbers compare numerically, text alphabetically."""
    parts = re.split(r"(\d+)", str(value))
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part != "")


env.globals.update(
    url_for=url_for,
    site_url=site_url,
    feed_abs=site_url("v1/feed.json"),
    products_abs=site_url("v1/products.json"),
    hardware_abs=site_url("v1/hardware.json"),
    vendor_index_abs=site_url(VENDOR_INDEX),
    human_date=human_date,
    human_datetime=human_datetime,
    human_stamp=human_stamp,
    plural=plural,
    # Month-precision helpers (AGENTS.md rule 4): a value that states a month is
    # never padded to a day, so the width of a published date is a template fact.
    is_month=is_month,
    month_end=month_end,
    published_period=published_period,
    source_link=source_link,
    source_name_for=source_name_for,
    source_attribution_for=source_attribution_for,
    endoflife_date_record=endoflife_date_record,
    base_path=BASE_PATH,
    repository_url=REPOSITORY_URL,
    source_name=SOFTWARE_SOURCE.name,
    source_site=SOFTWARE_SOURCE.url,
    source_license=SOURCE_LICENSE,
    source_license_url=SOURCE_LICENSE_URL,
    hardware_source_name=EOSL_SOURCE.name,
    hardware_source_site=EOSL_SOURCE.url,
    hardware_source_attribution=EOSL_SOURCE.attribution,
    catalog_source_name=OPENGEAR_SOURCE.pages[0].label,
    catalog_source_site=OPENGEAR_SOURCE.pages[0].url,
    # Vendor pages other than the catalogue's, by the name the registry gives
    # them, so templates link the source instead of restating its URL.
    opengear_lifecycle_page=OPENGEAR_SOURCE.pages[1],
    vendor_index_url=url_for(VENDOR_INDEX),
)
