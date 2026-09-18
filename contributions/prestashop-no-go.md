# PrestaShop — lifecycle investigation: NO-GO

Disposition for the PrestaShop lifecycle investigation (master tracker #13).
Recorded 2026-09-17. Scope: PrestaShop (the e-commerce platform), all versions.

## Decision

**NO-GO for a dated lifecycle record.** PrestaShop publishes GitHub release
tags with publication dates (latest: 9.1.5, 2026-08-18) but no version-specific
end-of-life, end-of-support, or retirement date. The project's support/lifecycle
pages return HTTP 404.

Tier under AGENTS.md rule 8: (a) deterministic — fails, no API and no
lifecycle table to collect; (b) researched — fails, no authoritative primary
source states an explicit EOL date; (c) absent — stands.

## Sources checked (fetched live, HTTP 200/404, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://github.com/PrestaShop/PrestaShop/releases` | GitHub release tags with publication dates (latest: 9.1.5, 2026-08-18) | Release dates only; no EOL or support-end dates |
| `https://build.prestashop.com/` | Project development blog with release announcements | No per-version EOL dates; "maintenance" mentioned in blog context only |
| `https://www.prestashop.com/en` | Project home page | No lifecycle or EOL statement for specific versions |
| `https://www.prestashop.com/en/support` | Support page | HTTP 404 — not available |
| `https://www.prestashop.com/en/pricing` | Pricing page | HTTP 404 — not available |
| `https://build.prestashop.com/news/2024/09/prestashop-8-2-0-and-prestashop-1-7-8-28-end-of-life/` | EOL announcement | HTTP 404 — not available |
| `https://endoflife.date/api/all.json` | 475 product slugs | No `prestashop` slug present |

## Verbatim evidence

Stored here so the decision can be re-read at its sources; every sentence below
was confirmed to appear verbatim in the live page text on 2026-09-17.

- `https://github.com/PrestaShop/PrestaShop/releases` (GitHub releases API)
  > Tag: 9.1.5, Published: 2026-08-18
  > Tag: 8.2.8, Published: 2026-08-18
  > Tag: 9.2.0-beta.1, Published: 2026-07-22
  > (100 releases total)

- `https://build.prestashop.com/`
  > No per-version EOL or support-end dates stated. Only release announcements
  with blog headlines like "PrestaShop Core Monthly."

- `https://www.prestashop.com/en/support`
  > HTTP 404 Not Found

- `https://www.prestashop.com/en/pricing`
  > HTTP 404 Not Found

- `https://build.prestashop.com/news/2024/09/prestashop-8-2-0-and-prestashop-1-7-8-28-end-of-life/`
  > HTTP 404 Not Found

## Why PrestaShop release dates were not converted into EOL dates

PrestaShop's GitHub release tags record only publication dates (e.g., "9.1.5,
Published: 2026-08-18") with no accompanying support window or EOL commitment.
No per-version support policy document exists on the public website. The project
site's support and pricing pages return HTTP 404, and a suspected EOL announcement
blog post URL also returns HTTP 404. There is no statement like "versions are
supported for N months after release" or "only the latest two major versions are
maintained." Release dates alone are not EOL dates.

## Source limitations

1. No per-version lifecycle or EOL table exists anywhere in PrestaShop's public
   documentation as of 2026-09-17, so there is no date to collect and no quote
   to store as a researched contribution.
2. `https://www.prestashop.com/en/support` and
   `https://www.prestashop.com/en/pricing` return HTTP 404, blocking access to
   any potential lifecycle pages.
3. `https://endoflife.date/api/all.json` returns no `prestashop` slug (checked
   2026-09-17), confirming no upstream community record to extend.
4. No `data/products/prestashop.json` record exists in the catalog.

## Reopen condition

Reopen when PrestaShop publishes an authoritative, day-precision statement tying
a named version to a lifecycle end — e.g., a per-version EOL table on
`prestashop.com`, or a vendor notice naming a version and its support-end or
retirement date. At that point the date is a tier (b) researched contribution
(or tier (a) if a table appears that a collector can re-derive). Until then
the product stays absent from the catalog, with release dates available from
PrestaShop's GitHub releases.

## No record published

No `prestashop` contribution file and no entry under `data/products/` were
created. The catalog is unchanged.
