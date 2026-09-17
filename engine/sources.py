"""The source registry: one descriptor per deterministic source of the catalog.

Every published record carries ``provenance.verifier`` naming the pipeline that
parsed it, and every pipeline owns exactly one slice of the catalog: the
endoflife.date software importer, the eosl.date hardware collector, the
Opengear lifecycle/configurator collector. Those facts used to be restated
wherever they were needed — a URL-to-label table in the site, an ``if verifier
== "deterministic-opengear"`` branch in validation, a list of vendor steps in
the publish workflow — which meant a new source had to be remembered in four
places. Here they are declared once, as data:

* ``id`` — the CLI command that refreshes this source (``import-opengear``).
* ``module``/``entry`` — the callable that does the refresh, imported lazily so
  enumerating sources never imports a network module.
* ``verifier``/``category`` — the provenance this source owns and the catalog
  it writes into. Validation requires a committed record's verifier to name a
  registered source *and* that source's category to match the record, so a
  hardware record can never claim the software importer and vice versa.
* ``name``/``url``/``urls``/``attribution`` — the presentation facts: what the
  source is called, where it lives, every page a refresh reads, and the
  sentence the site credits it with. The site never restates these.

Adding a vendor source is therefore additive: register a descriptor (and, if
the source re-derives its records offline, a ``validator`` path) and the CLI,
the refresh transaction and site attribution all pick it up without a list to
edit. The module imports nothing from the rest of ``engine``.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from urllib.parse import urlparse

# Upstream pages. Defined once here; the collectors import them rather than
# restating a URL that the registry and the site also publish.
ENDOFLIFE_DATE_API = "https://endoflife.date/api/v1/products/"
ENDOFLIFE_DATE_SITE = "https://endoflife.date/"
EOSL_DATE = "https://eosl.date/"
EOSL_DATE_SITEMAP = "https://eosl.date/sitemap-coreapp-product-families.xml"
OPENGEAR_LIFECYCLE = "https://opengear.com/end-life-products"
OPENGEAR_CONFIGURE = "https://opengear.com/configure/"
NVIDIA_VGPU_DOCS = "https://docs.nvidia.com/vgpu/index.html"

# Attribution is published text (the site and the API docs print it verbatim):
# eosl.date states no license for the data it republishes, so it is cited;
# Opengear's own pages are credited as the vendor's.
EOSL_ATTRIBUTION = ("Hardware lifecycle data comes from eosl.date by Subash Geetha Krishnan, "
                    "aggregated from public vendor announcements.")
OPENGEAR_ATTRIBUTION = ("Lifecycle dates published directly by Opengear; grouped parts and contract "
                        "exceptions are retained below.")
ENDOFLIFE_DATE_ATTRIBUTION = ("Software lifecycle data comes from endoflife.date, a community catalog of "
                              "public vendor lifecycle statements, used under its MIT license.")
NVIDIA_ATTRIBUTION = ("NVIDIA vGPU software branch lifecycle published directly by NVIDIA; "
                      "dates carry the month precision the vendor's table states.")
# A researched record's verifier names a contributor, not a pipeline: the
# registry leaves those to engine.contribute, which admits them against their
# own stored citation.
RESEARCHED_PREFIX = "researched-"


class RegistryError(ValueError):
    """A registry lookup or contract violation."""


class UnknownVerifier(RegistryError):
    """A committed record names a deterministic verifier no source registered."""


class UnknownSource(RegistryError):
    """No source is registered under that CLI command id."""


class CategoryMismatch(RegistryError):
    """A record claims a registered source that owns a different catalog."""


@dataclass(frozen=True)
class Page:
    """One page a source's refresh reads, and the label the site credits it with."""

    url: str
    label: str


@dataclass(frozen=True)
class Source:
    """One deterministic source of the catalog."""

    id: str
    module: str
    entry: str
    verifier: str
    category: str
    name: str
    url: str
    pages: tuple[Page, ...]
    attribution: str
    # Optional per-source paths, filled in only where the source has them:
    # `validator` is the dotted callable re-deriving one of its records offline,
    # `report` the sidecar file (relative to the data directory) its refresh
    # publishes to account for every source row it saw.
    validator: str = ""
    report: str = ""

    @property
    def urls(self):
        """Every page URL this source's refresh reads."""
        return tuple(page.url for page in self.pages)

    def run(self, directory=None):
        """Refresh this source into ``directory`` (the data directory).

        The implementation module is imported here, not at registration, so a
        process that only needs the registry (validation, a site build, the CLI
        help) never imports an HTTP client. Returns the source's own one-line
        summary of what it did.
        """
        module = importlib.import_module(self.module)
        return getattr(module, self.entry)(directory)


SOURCES = (
    Source(
        id="import-data",
        module="engine.importer",
        entry="import_data",
        verifier="deterministic-endoflife-date-v1",
        category="software",
        name="endoflife.date",
        url=ENDOFLIFE_DATE_SITE,
        pages=(Page(ENDOFLIFE_DATE_SITE, "endoflife.date"),
               Page(ENDOFLIFE_DATE_API, "endoflife.date API")),
        attribution=ENDOFLIFE_DATE_ATTRIBUTION,
    ),
    Source(
        id="import-hardware",
        module="engine.hardware",
        entry="import_hardware",
        verifier="deterministic-eosl-date",
        category="hardware",
        name="eosl.date",
        url=EOSL_DATE,
        pages=(Page(EOSL_DATE, "eosl.date"),
               Page(EOSL_DATE_SITEMAP, "eosl.date product family sitemap")),
        attribution=EOSL_ATTRIBUTION,
    ),
    Source(
        id="import-opengear",
        module="engine.opengear",
        entry="import_opengear",
        verifier="deterministic-opengear",
        category="hardware",
        name="Opengear",
        url=OPENGEAR_LIFECYCLE,
        # The configurator leads: a catalog record is read from the listing that
        # carries its SKU, and a lifecycle row from the retirement table.
        pages=(Page(OPENGEAR_CONFIGURE, "Opengear product configurator"),
               Page(OPENGEAR_LIFECYCLE, "Opengear end-of-life product list")),
        attribution=OPENGEAR_ATTRIBUTION,
        # Opengear records re-derive themselves from their own stored cells, so
        # the registry is where validation finds that per-source check; its
        # refresh also publishes the per-row accounting sidecar below.
        validator="engine.opengear.validate_record",
        report="opengear-import.json",
    ),
    Source(
        id="import-vgpu",
        module="engine.vgpu",
        entry="import_vgpu",
        verifier="deterministic-nvidia-vgpu",
        category="software",
        name="NVIDIA vGPU docs",
        url=NVIDIA_VGPU_DOCS,
        pages=(Page(NVIDIA_VGPU_DOCS, "NVIDIA vGPU software lifecycle"),),
        attribution=NVIDIA_ATTRIBUTION,
        # Every stored milestone re-derives from the record's own stored cells,
        # and the refresh accounts for every branch row it saw.
        validator="engine.vgpu.validate_record",
        report="vgpu-import.json",
    ),
)

# Registry id -> source, and verifier -> source: one source per verifier, which
# is what makes a refresh's ownership slice well defined.
BY_ID = {source.id: source for source in SOURCES}
BY_VERIFIER = {source.verifier: source for source in SOURCES}
if len(BY_ID) != len(SOURCES) or len(BY_VERIFIER) != len(SOURCES):
    raise RegistryError("Duplicate source id or verifier")
# Page URL -> label, exact match first, then the site root it belongs to.
PAGES = {page.url: page.label for source in SOURCES for page in source.pages}


def all_sources():
    """Every registered source, in refresh order."""
    return SOURCES


def source(source_id):
    """The source registered under a CLI command id."""
    try:
        return BY_ID[source_id]
    except KeyError:
        raise UnknownSource(f"No source registered as {source_id!r}") from None


def source_for(verifier):
    """The source owning ``verifier``; raises for an unregistered one.

    This is the enforcement path: a deterministic verifier that no source
    registered means a record claims a pipeline that is not installed, so the
    catalog would not be reproducible from this checkout.
    """
    try:
        return BY_VERIFIER[verifier]
    except KeyError:
        raise UnknownVerifier(
            f"Unknown deterministic verifier {verifier!r}; register the source in engine/sources.py "
            f"or mark the record as researched") from None


def sources_for(verifier):
    """Every source owning ``verifier``; empty for researched or unknown ones.

    The presentation path: a researched record's verifier names a contributor,
    not a pipeline, and its citation is its own — so the callers that render or
    attribute a record ask here and fall back, while validation asks
    :func:`source_for` and refuses.
    """
    found = BY_VERIFIER.get(verifier)
    return (found,) if found else ()


def verify_category(verifier, category):
    """The source owning ``verifier``, once its catalog matches ``category``."""
    found = source_for(verifier)
    if found.category != category:
        raise CategoryMismatch(
            f"Verifier {verifier!r} owns the {found.category} catalog, not {category}")
    return found


def source_urls(verifier):
    """Every page URL the source owning ``verifier`` reads."""
    return tuple(page.url for source in sources_for(verifier) for page in source.pages)


def source_label(url):
    """The label for a published source URL, or its hostname when unrecognised.

    Records carry per-page source URLs (a record's own page, the notice that
    named it, a vendor PDF), so labels cannot be enumerated per record; the
    registry labels the pages it knows and the fallback names the host honestly.
    """
    if url in PAGES:
        return PAGES[url]
    for page, label in PAGES.items():
        if url.startswith(page):
            return label
    if "//" in url:
        host = urlparse(url).hostname or url
        return host[4:] if host.startswith("www.") else host
    return url


def attribution(verifier):
    """The attribution sentence for a verifier's source, else an empty string."""
    found = BY_VERIFIER.get(verifier)
    return found.attribution if found else ""


def record_validator(found):
    """The per-record validator of a source that re-derives its own records.

    Imported lazily so validation pulls in a collector only for records that
    collector owns.
    """
    if not found.validator:
        return None
    module, _, name = found.validator.rpartition(".")
    return getattr(importlib.import_module(module), name)


def validate_verifier(verifier, category):
    """Check a committed record's verifier against the registry.

    Returns the owning source, or None when the verifier is not the registry's
    business: a ``researched-<contributor>`` verifier names a contribution, not
    a pipeline, and ``engine.contribute`` admits those against their own stored
    citation. Anything else must be a registered source owning ``category``,
    which is what stops a record claiming a pipeline this checkout does not
    install — or a pipeline that owns a different catalog.
    """
    if not isinstance(verifier, str) or not verifier:
        raise UnknownVerifier("Record without a verifier")
    if verifier.startswith(RESEARCHED_PREFIX):
        return None
    return verify_category(verifier, category)
