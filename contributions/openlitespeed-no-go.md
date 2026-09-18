# OpenLiteSpeed — lifecycle investigation: NO-GO

Disposition for the OpenLiteSpeed lifecycle investigation (master tracker #13).
Recorded 2026-09-17. Scope: OpenLiteSpeed (open-source edition), not the
commercial LiteSpeed Enterprise.

## Decision

**NO-GO for a dated lifecycle record.** OpenLiteSpeed publishes version
categories (Latest, Stable, Archived) but no explicit end-of-life, end-of-support,
or retirement dates for any version.

Tier under AGENTS.md rule 8: (a) deterministic — fails, no API and no lifecycle
table to collect; (b) researched — fails, no authoritative primary source states
an explicit EOL date; (c) absent — stands.

## Sources checked (all fetched live, HTTP 200, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://openlitespeed.org/release-log` | Version status categories: "1.9.x Latest, 1.8.x Stable, 1.7.x Archived" | Version categories only — no explicit EOL dates |
| `https://openlitespeed.org/` | Project home, documentation, and download pages | No lifecycle or EOL statement for specific versions |
| `https://github.com/litespeedtech/openlitespeed/tags` | GitHub release tags | Release tags only; no EOL policy |

## Verbatim evidence

Stored here so the decision can be re-read at its sources; every sentence below
was confirmed to appear verbatim in the live page text on 2026-09-17.

- `openlitespeed.org/release-log`
  > As of September 2025, OpenLiteSpeed version 1.7.x is archived and no longer
  > maintained. Please upgrade to version 1.8.x or 1.9.x.

- `openlitespeed.org/release-log`
  > 1.9.x Latest 1.8.x Stable 1.7.x Archived

## Why version categories were not converted into dates

OpenLiteSpeed uses relative version categories rather than dated lifecycle
milestones:

| Statement | Source | Why it is not a stored date |
| --- | --- | --- |
| "1.9.x Latest" | release-log | Branch position, not a date |
| "1.8.x Stable" | release-log | Branch position, not a date |
| "1.7.x Archived" | release-log | Branch position, not a date |
| "1.7.x is archived and no longer maintained. Please upgrade to 1.8.x or 1.9.x." | release-log | States the branch is unmaintained but names no EOL date — no calendar day is published |

The "Archived" and "no longer maintained" statements describe support status
without tying any version to a dated end-of-life. The vendor explicitly states
the category of each branch but never publishes a specific date when support
ended or when it will end.

## Source limitations

1. No per-version lifecycle or EOL table with dates exists anywhere in
   OpenLiteSpeed's documentation as of 2026-09-17, so there is no date to
   collect and no quote to store as a researched contribution.
2. `https://endoflife.date/api/all.json` returns no `openlitespeed` slug
   (checked 2026-09-17: no openlitespeed product), confirming no upstream
   community record to extend.
3. No `data/products/openlitespeed.json` record exists in the catalog.
4. OpenLiteSpeed is distinct from LiteSpeed Enterprise (which is tracked as
   `litespeedtech` in some upstream sources); this investigation covers only the
   open-source project.

## Reopen condition

Reopen when OpenLiteSpeed publishes an authoritative, day-precision statement
tying a named version to a lifecycle end — e.g., a per-version EOL table on
`openlitespeed.org`, or a vendor notice naming a version and its support-end or
retirement date. At that point the date is a tier (b) researched contribution
(or tier (a) if a table appears that a collector can re-derive). Until then
the product stays absent from the catalog.

## No record published

No `openlitespeed` contribution file and no entry under `data/products/` were
created. The catalog is unchanged.
