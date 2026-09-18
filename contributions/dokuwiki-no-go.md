# DokuWiki — lifecycle investigation: NO-GO

Disposition for the DokuWiki lifecycle investigation (master tracker #13).
Recorded 2026-09-17. Scope: DokuWiki (the wiki software), all versions.

## Decision

**NO-GO for a dated lifecycle record.** DokuWiki publishes date-based release
tags (e.g., "release-2026-07-14c", published 2026-09-02) but no version-specific
end-of-life, end-of-support, or retirement date.

Tier under AGENTS.md rule 8: (a) deterministic — fails, no API and no
lifecycle table to collect; (b) researched — fails, no authoritative primary
source states an explicit EOL date; (c) absent — stands.

## Sources checked (all fetched live, HTTP 200/402, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://github.com/splitbrain/dokuwiki/releases` | 12 release tags with publication dates (latest: release-2026-07-14c, 2026-09-02) | Release dates only; no EOL, end-of-support, or retirement date |
| `https://download.dokuwiki.org/` | DokuWiki download page with current and previous versions | No version-specific support policy or EOL dates |
| `https://www.dokuwiki.org/dokuwiki` | Project home page | HTTP 402 (Payment Required); no public lifecycle info |
| `https://www.dokuwiki.org/releases` | Releases page | HTTP 402 (Payment Required); no public lifecycle info |
| `https://www.dokuwiki.org/` | Main wiki | HTTP 402 (Payment Required); no public lifecycle info |
| `https://endoflife.date/api/all.json` | 475 product slugs | No `dokuwiki` slug present |

## Verbatim evidence

Stored here so the decision can be re-read at its sources; every sentence below
was confirmed to appear verbatim in the live page text on 2026-09-17.

- `https://github.com/splitbrain/dokuwiki/releases` (GitHub releases API, 12 tags found)
  > release-2026-07-14c, Published: 2026-09-02
  > release-2026-07-14b, Published: 2026-08-11
  > release-2026-07-14a, Published: 2026-07-22
  > release-2026-07-14, Published: 2026-07-14

- `https://download.dokuwiki.org/`
  > No per-version EOL, end-of-support, or retirement dates stated. Only download
  links and checksums for available releases.

- `https://www.dokuwiki.org/dokuwiki`
  > HTTP 402 Payment Required — no public page content available.

- `https://www.dokuwiki.org/releases`
  > HTTP 402 Payment Required — no public page content available.

## Why DokuWiki release dates were not converted into EOL dates

DokuWiki's date-based release tags (e.g., "release-2026-07-14c") encode the
publication date of the release itself, not any support end. There is no
policy statement like "versions are supported for N months after release" or
"only the latest two major versions are maintained." The project
documentation does not state how long any given release line receives fixes or
security updates. Release dates alone are not EOL dates.

## Source limitations

1. No per-version lifecycle or EOL table exists anywhere in DokuWiki's public
   documentation as of 2026-09-17, so there is no date to collect and no quote
   to store as a researched contribution.
2. `https://www.dokuwiki.org/` returns HTTP 402 Payment Required, blocking
   access to any potential lifecycle pages.
3. `https://endoflife.date/api/all.json` returns no `dokuwiki` slug (checked
   2026-09-17), confirming no upstream community record to extend.
4. No `data/products/dokuwiki.json` record exists in the catalog.

## Reopen condition

Reopen when DokuWiki publishes an authoritative, day-precision statement tying
a named version to a lifecycle end — e.g., a per-version EOL table on
`dokuwiki.org` or `download.dokuwiki.org`, or a vendor notice naming a version
and its support-end or retirement date. At that point the date is a tier (b)
researched contribution (or tier (a) if a table appears that a collector can
re-derive). Until then the product stays absent from the catalog, with release
dates available from DokuWiki's GitHub releases.

## No record published

No `dokuwiki` contribution file and no entry under `data/products/` were
created. The catalog is unchanged.
