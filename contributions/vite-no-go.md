# Vite — lifecycle investigation: NO-GO

Disposition for the Vite lifecycle investigation (master tracker #13).
Recorded 2026-09-17. Scope: Vite (core) 5.x and 6.x, the build tool. Vite
plugins and ecosystem packages are not covered.

## Decision

**NO-GO for a dated lifecycle record.** Vite publishes a relative support
policy but no version-specific end-of-life, end-of-support, or retirement date.

Tier under AGENTS.md rule 8: (a) deterministic — fails, no API and no lifecycle
table to collect; (b) researched — fails, no authoritative primary source states
an explicit EOL date; (c) absent — stands.

## Sources checked (all fetched live, HTTP 200, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://vite.dev/releases` | Support policy page with relative branch windows | Relative policy only — no explicit version-specific EOL dates. States "Current Minor, Previous Major, Previous Minor, Second-to-last Major" support windows |
| `https://vite.dev/` | Project home and documentation | No lifecycle or EOL statement for specific versions |
| `https://github.com/vitejs/vite/releases` | GitHub release tags with dates | Release dates only; no EOL policy |

## Verbatim evidence

Stored here so the decision can be re-read at its sources; every sentence below
was confirmed to appear verbatim in the live page text on 2026-09-17.

- `vite.dev/releases`
  > Current Minor: Full feature support and bug fixes
  > Previous Major: Critical bug fixes
  > Previous Minor: Critical bug fixes
  > Second-to-last Major: Critical bug fixes
  > Older versions: No support

- `vite.dev/releases`
  > The support policy is based on the release cadence and the latest stable
  > version.

## Why the relative statements were not converted into dates

Every quantity Vite states is relative to "the latest version" or named branch
positions — never a fixed calendar day for a named version:

| Statement | Source | Why it is not a stored date |
| --- | --- | --- |
| "Current Minor: Full feature support and bug fixes" | vite.dev/releases | Relative branch position, not a date |
| "Previous Major: Critical bug fixes" | vite.dev/releases | Relative branch position, not a date |
| "Older versions: No support" | vite.dev/releases | Relative cutoff, not a date |
| "support policy is based on the release cadence and the latest stable version" | vite.dev/releases | Relative to the latest version, not a fixed calendar day |

`contributions/README.md` states the rule directly: "A rolling support policy
('only the latest minor branch is maintained') is evidence that no end date
exists, never a date in itself." Vite's policy is that shape.

## Source limitations

1. No per-version lifecycle or EOL table exists anywhere in Vite's documentation
   as of 2026-09-17, so there is no date to collect and no quote to store as a
   researched contribution.
2. `https://endoflife.date/api/all.json` returns no `vite` slug (checked
   2026-09-17: no vite product), confirming no upstream community record to
   extend.
3. No `data/products/vite.json` record exists in the catalog.

## Reopen condition

Reopen when Vite publishes an authoritative, day-precision statement tying a
named version to a lifecycle end — e.g., a per-version EOL table on
`vite.dev/releases`, or a vendor notice naming a version and its support-end or
retirement date. At that point the date is a tier (b) researched contribution
(or tier (a) if a table appears that a collector can re-derive). Until then the
product stays absent from the catalog, with release dates available from Vite's
GitHub releases.

## No record published

No `vite` contribution file and no entry under `data/products/` were created.
The catalog is unchanged.
