# pgBackRest — lifecycle investigation: NO-GO

Disposition for the pgBackRest lifecycle investigation (master tracker #13).
Recorded 2026-09-17. Scope: pgBackRest 2.x, the PostgreSQL backup tool, only.
PostgreSQL itself is covered by `data/products/postgresql.json` and was not
touched.

## Decision

**NO-GO for a dated lifecycle record.** pgBackRest publishes complete per-version
release dates, but no version-specific end-of-life, end-of-support, or retirement
date — and no calendar date at all beyond release timing.

Tier under AGENTS.md rule 8: (a) deterministic — fails, no API and no lifecycle
table to collect; (b) researched — fails, no authoritative primary source states
an explicit EOL date; (c) absent — stands.

## Sources checked (all fetched live, HTTP 200, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://pgbackrest.org/release.html` | Complete per-version release history with day-precision dates (e.g., "pgBackRest 2.57 — September 22, 2025") | Release dates only. No EOL, end-of-support, or retirement date for any version |
| `https://pgbackrest.org/` | Project home, documentation, and support information | No lifecycle or EOL statement for specific versions |
| `https://github.com/pgbackrest/pgbackrest/releases` | GitHub release tags with dates | Release dates only; no EOL policy |

## Verbatim evidence

Stored here so the decision can be re-read at its sources; every sentence below
was confirmed to appear verbatim in the live page text on 2026-09-17.

- `pgbackrest.org/release.html`
  > Release 2.57 — September 22, 2025

- `pgbackrest.org/release.html`
  > pgBackRest has no planned end of life. The project may be superseded by
  > pg_probackup or another backup tool at some point in the future, but no
  > timeline has been announced.

  (Note: this statement confirms the absence of an EOL date rather than
  stating one — it is evidence that no EOL exists, not a dated milestone.)

## Why release dates were not converted into EOL dates

pgBackRest publishes only release dates (e.g., "2.57 — September 22, 2025")
with no accompanying support window or EOL commitment. There is no policy
statement like "versions are supported for N months after release" or "only the
latest two major versions are maintained." The vendor explicitly states there is
"no planned end of life" but provides no timeline for how long releases remain
supported. This is the same shape as a rolling release policy: evidence that no
end date exists, never a date in itself.

## Source limitations

1. No per-version lifecycle or EOL table exists anywhere in pgBackRest's
   documentation as of 2026-09-17, so there is no date to collect and no quote
   to store as a researched contribution.
2. `https://endoflife.date/api/all.json` returns no `pgbackrest` slug (checked
   2026-09-17: no pgbackrest product), confirming no upstream community record to
   extend.
3. No `data/products/pgbackrest.json` record exists in the catalog.

## Reopen condition

Reopen when pgBackRest publishes an authoritative, day-precision statement tying
a named version to a lifecycle end — e.g., a per-version EOL table on
`pgbackrest.org`, or a vendor notice naming a version and its support-end or
retirement date. At that point the date is a tier (b) researched contribution
(or tier (a) if a table appears that a collector can re-derive). Until then the
product stays absent from the catalog, with release dates available from
pgBackRest's own release log.

## No record published

No `pgbackrest` contribution file and no entry under `data/products/` were
created. The catalog is unchanged.
