# SolarWinds `ga` coverage — the scope decision

Recorded 2026-09-26, against issue #119 ("Scope `ga` coverage from release-note
Release date lines"). The issue asked for the enumeration *before* the decision,
so that `ga` is not promised on a guess.

## What the enumeration says

Counted from the vendor's own sitemap (`documentation.solarwinds.com/sitemap.xml`,
8,017 URLs, fetched 2026-09-26), matching the per-version release-note pages
under each family's `content/release_notes/`:

* **729 release-note pages across 37 product directories.**
* The density is per-release, not per-family: ARM has 19, EOC 27, IPAM 27,
  ETS-web 27, DPA 17, ETS-desk 15, Dameware 14, DRE 11, Incident Response 8,
  KCT-legacy 6, KCT 5, Database Mapper 2.

So `ga` coverage is a ~730-page crawl of MadCap pages, each of which states a
"Release date: <day>" line in prose, at day precision, with no table to reconcile
against. Confirmed on two pages: DPA 2026.2 states "Release date: June 30,
2026" and SolarWinds Platform 2026.2 states "Release date: June 9, 2026".

## Decision: out of scope for this collector, and why

`deterministic-solarwinds` publishes **`ga: null` for every release**, and says
so in its report. The reasons:

1. **It is a different source, not a column of this one.** A release-history
   table states no release date. Reading the date from a *different* page per
   release means the record's evidence spans 30 tables and 730 pages, and every
   one of those pages would have to be re-fetched and re-validated on each
   refresh to keep the dates honest. That is its own source with its own
   verifier, its own report and its own failure mode — not a field of this one.
2. **A day-precision date read from prose is a new parsing risk.** The
   release-note pages are the same MadCap output as the tables, but the date
   lives in a sentence, next to a "Last Updated" header and a feedback widget.
   A `ga` wrong by one release is a wrong general-availability date in a feed
   and in OpenEoX; the failure is silent and the cost is high.
3. **The value is low against the cost.** The pages that state a release date
   are the *current* releases. The 509 published releases are overwhelmingly
   already past their `eol`; a `ga` for a release that ended years ago changes
   no decision a reader makes from this catalog. The `ga` that matters —
   "when did the release I am running ship?" — is answered by the vendor's own
   release notes, which the record links to.

## What is published instead

Each record's `links.html` is the family page, and `upstream.cells` keeps the
vendor's own cells verbatim, so a reader who needs the release date reads it
from the vendor. The report's first limitation states the gap in full.

## Reopening

If `ga` is wanted, the honest shape is a second source —
`deterministic-solarwinds-ga` — that fetches the 729 pages, requires the
"Release date:" sentence verbatim on every page (refusing a page that drops it),
publishes the day at the precision the sentence states, and accounts for every
page it fetched in its report, including the per-family pages that state no
date. That is a day of work and roughly 730 polite requests per refresh; it is
worth doing only if a reader actually needs a machine-readable GA day for a
release that is still supported.
