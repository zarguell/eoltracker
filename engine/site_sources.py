"""Source attribution: which source published a record, and which page it was read from.

A record carries verifier ids and the exact page URLs it was fetched from
(`provenance.source_urls`); it does not carry its source's presentation. This
module turns those into what a page prints — a readable label per page, the page
a record is considered read from, the source's name and its attribution
sentence — by asking `engine.sources`, the registry that also owns discovery,
refresh and validation.

Nothing here restates a vendor. There is no table of source names, no URL to
label mapping and no per-vendor branch: a new collector registers itself once in
the registry and the site credits it, links it and labels its pages. The only
rule this module owns is the reading order of a record's source list, and even
that reads the registry's own `Source.pages` order rather than naming a page.
"""
from .site_config import EOSL_SOURCE
from . import sources


def source_name(verifier):
    """The published name of the source behind one verifier.

    A researched record has no registered collector — its verifier names a
    contributor, not a pipeline — so it is not credited to a source that never
    read it. The eosl.date name stands in for those, matching the credit the
    hardware catalog as a whole carries.
    """
    registered = sources.sources_for(verifier)
    return registered[0].name if registered else EOSL_SOURCE.name


def source_attribution(verifier):
    """The credit sentence published for a record's source."""
    registered = sources.sources_for(verifier)
    return registered[0].attribution if registered else EOSL_SOURCE.attribution


def source_label(url):
    """A readable name for one source page.

    The registry names every page its collectors fetch — including two pages of
    one vendor, which a bare host would label identically — so a URL the
    registry knows is labelled with that source's own wording. Anything it does
    not know (a record's own linked notice, a vendor PDF) falls back to its
    host, which is still a true statement about where the link goes.
    """
    return sources.source_label(url)


def source_links(urls):
    """Page links for a record or a page that lists several sources."""
    return [{"url": url, "label": source_label(url)} for url in urls]


def is_catalog_record(record):
    """True for an exact catalogue model.

    The contract's marker is the presence of the optional `catalog` /
    `lifecycle` fields — `family` naming the record `catalog` is the same fact
    stated for readers. Presence decides, so a record is never treated as a
    lifecycle row merely because its family is spelled differently.
    """
    return record.get("catalog") is not None or record.get("lifecycle") is not None


def primary_page(record):
    """The page a record is considered read from, or None when that page is not a fact.

    A collector registers its pages in the order it reads them, so the leading
    page is the one that carries the record: for a catalogue model, the listing
    that published its exact model string; for a lifecycle row, the table the
    row was parsed from. Researched records register no pages, so they keep the
    order their citation recorded.
    """
    if not is_catalog_record(record):
        return None
    return primary_url(record["provenance"]["verifier"])


def primary_url(verifier):
    """The leading page of a verifier's source, or None when it registered none."""
    registered = sources.sources_for(verifier)
    return registered[0].pages[0].url if registered and registered[0].pages else None


def primary_label(verifier):
    """The label of a verifier's leading page, or None when it registered none."""
    registered = sources.sources_for(verifier)
    return registered[0].pages[0].label if registered and registered[0].pages else None


def source_order(record):
    """The record's source pages, with the page it was actually read from first.

    A catalogue record is read from the vendor's product listing, so that page
    leads its source list even after a notice names the exact model — the notice
    is additional evidence, not a replacement for where the record came from. A
    lifecycle row keeps the order its parser recorded, so a notice page is never
    promoted ahead of the table the row was parsed from.
    """
    urls = list(record["provenance"]["source_urls"])
    primary = primary_page(record)
    if primary:
        urls = [primary] + [url for url in urls if url != primary]
    return urls
