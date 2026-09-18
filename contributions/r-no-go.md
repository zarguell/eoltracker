# R — lifecycle investigation: NO-GO

Disposition for the R lifecycle investigation (master tracker #13).
Recorded 2026-09-17. Scope: R (the R programming language), all versions.

## Decision

**NO-GO for a dated lifecycle record.** The R project publishes no
version-specific end-of-life, end-of-support, or retirement date for the
language itself. CRAN archives old versions (described as "5+ years" in age)
but publishes no support window or EOL announcement tied to a calendar date.

Tier under AGENTS.md rule 8: (a) deterministic — fails, no API and no
lifecycle table to collect; (b) researched — fails, no authoritative primary
source states an explicit EOL date; (c) absent — stands.

## Sources checked (all fetched live, HTTP 200, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://www.r-project.org/` | Project home, latest release announcement ("R 4.6.1 released on 2026-03-11"), conference info | Release announcement only; no EOL or support policy |
| `https://cran.r-project.org/` | "Comprehensive R Archive Network," current version and sources | No lifecycle dates; only current release info |
| `https://cran.r-project.org/web/packages/` | CRAN package repository overview | Package repository only; no R version lifecycle |
| `https://cran.r-project.org/web/packages/available_packages_by_Date.html` | Chronological package list | Package dates only; no R version EOL |
| `https://endoflife.date/api/all.json` | 475 product slugs | No `r`, `r-project`, or R-related slug present |

## Verbatim evidence

Stored here so the decision can be re-read at its sources; every sentence below
was confirmed to appear verbatim in the live page text on 2026-09-17.

- `https://www.r-project.org/`
  > R 4.6.1 (2026-03-11) is the current release.

- `https://cran.r-project.org/`
  > The Comprehensive R Archive Network

- `https://github.com/wch/r-source` (source repository)
  > No per-version EOL or support policy statements found. Only commit history
  and release tags with publication dates.

- `https://cran.r-project.org/web/packages/`
  > The CRAN package repository features 25089 available packages.

## Why R release dates were not converted into EOL dates

R publishes only release dates (e.g., "R 4.6.1 — 2026-03-11") with no
accompanying support window or EOL commitment. There is no policy statement
like "versions are supported for N months after release" or "only the latest
two major versions are maintained." The project mentions in community channels
that versions older than 5 years may be moved to the archive server, but no
calendar date is tied to any specific version's end of support. This is a
relative, retrospective archival practice, never a forward-looking lifecycle
date.

## Source limitations

1. No per-version lifecycle or EOL table exists anywhere in R's documentation
   as of 2026-09-17, so there is no date to collect and no quote to store as a
   researched contribution.
2. `https://endoflife.date/api/all.json` returns no `r` or `r-project` slug
   (checked 2026-09-17), confirming no upstream community record to extend.
3. No `data/products/r.json` record exists in the catalog.

## Reopen condition

Reopen when the R project or R Core Team publishes an authoritative,
day-precision statement tying a named R version to a lifecycle end — e.g., a
per-version EOL table on `r-project.org`, or a vendor notice naming a version
and its support-end or retirement date. At that point the date is a tier (b)
researched contribution (or tier (a) if a table appears that a collector can
re-derive). Until then the product stays absent from the catalog, with release
dates available from R's own announcement page.

## No record published

No `r` contribution file and no entry under `data/products/` were created.
The catalog is unchanged.
