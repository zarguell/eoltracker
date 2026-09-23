# AG Grid — lifecycle investigation: NO-GO

Recorded 2026-09-23. Scope: the AG Grid JavaScript product family, while
preserving its Community and Enterprise editions as distinct distributions.

## Decision

**NO-GO for a dated lifecycle record.** AG Grid publishes release dates, an LTS
maintenance commitment, current security-support status, and package metadata,
but no named release or branch has an explicit terminal date, fixed support
duration, or release-triggered support-end rule.

Tier under AGENTS.md rule 8: (a) deterministic — fails, the official archive
contains release documentation rather than a lifecycle table; (b) researched —
fails, no authoritative source states a terminal date or a calculable terminal
rule; (c) absent — stands. Release dates alone would not provide the lifecycle
fact this contribution is meant to record.

## Sources checked

| Official source | Evidence | Limit |
| --- | --- | --- |
| [Documentation archive](https://www.ag-grid.com/documentation-archive/) | "Browse archived documentation for previous AG Grid versions, from version 14 and onwards." Tables contain `Version`, `Date`, `Type`, `Documentation`, and `Changelog`. | Release dates and documentation only; no support or terminal-lifecycle column. |
| [LTS announcement](https://www.ag-grid.com/blog/introducing-long-term-support-for-ag-grid-and-ag-charts/) | "we will now maintain both `v32-lts` of AG Grid and `v10-lts` of AG Charts", including essential bug fixes and critical security patches. | No terminal date, duration, replacement trigger, or LTS interval. |
| [`SECURITY.md`](https://raw.githubusercontent.com/ag-grid/ag-grid/latest/SECURITY.md) | "We currently provide security updates for the following versions:" with checks for `32.x` and `36.x`. | Current status only; it gives neither an end-of-security-support nor an end-of-life date and does not call 36.x LTS. |
| [Community vs Enterprise](https://www.ag-grid.com/javascript-data-grid/community-vs-enterprise/) | Community has community-driven support; Enterprise has dedicated support and "Licences ... come with 1 year of support and updates." | Edition and commercial entitlement, not a product branch lifecycle. |
| [v33 package transition](https://www.ag-grid.com/javascript-data-grid/upgrading-to-ag-grid-33/) | Feature modules moved into `ag-grid-community` or `ag-grid-enterprise`; scoped packages were removed in 33.0. | Distribution history, not lifecycle evidence. |
| [Community package metadata](https://registry.npmjs.org/ag-grid-community) and [Enterprise package metadata](https://registry.npmjs.org/ag-grid-enterprise) | Both identify `v32-lts` as 32.3.9 and `latest` as 36.2.0; Community is MIT and Enterprise is commercial. Enterprise 36.2.0 depends on Community 36.2.0, and Enterprise 32.3.9 depends on Community 32.3.9. | Dist-tags, versions, licenses, and dependency relationships are not support endpoints. |

## Edition and support distinction

AG Grid says "AG Grid Community: Free for everyone, including production use"
and "AG Grid Enterprise: Requires a licence to use in production." Its support
page distinguishes community-driven support from Enterprise's dedicated support.
A future integration therefore must not merge the editions merely because
version numbers align. It must also preserve the pre-33 scoped-package layout
and the v33+ all-in-one package distinction.

The Enterprise license's one year of support and updates is a purchased
entitlement. It does not say that an AG Grid release stops being maintained
after one year, and it cannot populate `eossec` or `eol` for a named release.

## Why current support is not product EOL

The checked `32.x` and `36.x` entries say only that security updates are
currently provided. Likewise, the LTS announcement promises critical security
patches and stable maintenance for `v32-lts` "throughout their support
lifecycles." Neither statement gives a terminal date. Changing a checkmark in
`SECURITY.md`, publishing a newer release, changing an npm `latest` tag, or
knowing a commercial license's duration cannot be converted into a product EOL.

No reviewed source provides any of the following for a named AG Grid branch:

- a stated end-of-security-support or end-of-life date;
- a fixed support duration from a stated base date; or
- a release trigger that explicitly ends support.

Accordingly, there is no `milestone_provenance`-eligible duration or trigger and
no terminal milestone to store.

## Reconsideration criteria

Reconsider when AG Grid publishes an authoritative lifecycle policy or table
that maps a named Community or Enterprise release or branch to an explicit
terminal date, or states a fixed duration or release-triggered endpoint with a
named base. A deterministic table could then be collected automatically; a
prose statement could support a researched contribution only after preserving
the exact quote, source, and base. Reconsider separately if the distinction
between Community and Enterprise lifecycle scope changes.

Until one of those conditions is met, AG Grid remains absent rather than
receiving a fabricated EOL.
