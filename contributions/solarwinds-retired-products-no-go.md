# No-go: the SolarWinds retired-products table cannot be refreshed

Recorded 2026-09-26, against issue #118 ("Add a collector for the
retired-products lifecycle table"). The table exists, is public, and states
day-precision dates — and the host serving it refuses every request this
repository's collector makes.

## Decision

**No collector, no record, no code.** The release-history source ships
(`deterministic-solarwinds`, 30 product families, 509 releases); the
retired-products table does not, because a source that cannot be refreshed is a
record that silently rots. A parsed-but-unrefreshable table would be the
"manual copy of what automation can fetch" AGENTS.md rule 8(a) forbids.

## What was tried, and what came back

| Request (2026-09-26, `engine.net`, UA `eoltracker/1.0 (+https://github.com/zarguell/eoltracker)`) | Result |
| --- | --- |
| `https://support.solarwinds.com/SuccessCenter/s/article/Currently-supported-software-versions?language=en_US` | `403 Forbidden` |
| `https://support.solarwinds.com/SuccessCenter/s/article/Currently-supported-software-versions` | `403 Forbidden` |
| `https://support.solarwinds.com/robots.txt` | `403 Forbidden` |
| `https://documentation.solarwinds.com/en/success_center/ncm/content/release_notes/release_history.htm` | `200 OK` (the documentation host serves the same client fine) |

The block is host-wide and client-shaped, not a robots policy: the crawler is
refused the robots file itself. A browser reaches the page, and its table was
read once by hand to confirm what it states — but spoofing a browser identity to
get past a refusal is exactly the "respect robots/ToS" line AGENTS.md draws, so
it was not done.

## What the table states (read by hand, 2026-09-26, "Last published date 6/5/2026")

20 rows, columns `Product` / `Final version` / `EoL Announcement` /
`EoE Effective Date` / `EoL Effective Date`, each column carrying its own note —
the terminal one reads "The date SolarWinds stopped providing technical support
for the product", which is the same `eol` mapping the release histories use (see
`solarwinds-milestone-mapping.md`). Rows include AppOptics (EoL January 31,
2026), APS Sentry, CodeSlice, Database Mapper (EoL February 28, 2024 — the same
date its documentation page states), FoE, IPMonitor, LAN Surveyor (bare years
2012/2012/2013), Librato, Mobile Admin, SentryOne Test, SentryOneMonitor, SQL
Sentry Essentials, SRM Profiler/Storage Manager and Workbench. Alert Central
states `--` in every date cell.

Five of those products also appear in a documentation release history, so a
collector would have to reconcile two sources' vocabulary for the same product.

## What would change this decision

* A public, crawlable rendering of the same table on a host that serves
  non-browser clients — for example the vendor publishing it as a static page
  or a feed on `documentation.solarwinds.com`.
* A vendor-sanctioned API for the article.

Either would make this a tier-(a) deterministic source with its own verifier and
report, exactly as the release histories are. Until then the products stay
absent, and a reader is told so by this file rather than by a stale record.
