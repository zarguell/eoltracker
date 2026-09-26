# SolarWinds milestone mapping — the decision behind `deterministic-solarwinds`

Recorded 2026-09-26, against issues #116 (resolve the mapping) and #117 (the
release-history collector). The collector ships with this decision; this file is
the evidence it rests on.

## Decision

| Vendor column | Becomes | Why |
| --- | --- | --- |
| `EoL effective date` | `eol` | The vendor's own column note: "the date SolarWinds stopped providing technical support for the product". Terminal support end, day precision, stated. |
| `EoL announcement` | nothing | A notice to start transitioning. Not GA, not a sale end, not a support end. |
| `EoE effective date` | nothing | End of engineering: "service releases, bug fixes, workarounds, and service packs ... were no longer actively supported". SolarWinds never calls this a security-support end, so it never fills `eossec` (AGENTS.md milestone rules). Kept verbatim in `upstream.cells`. |
| `EoS effective date` | nothing | Absent from the release histories. The End of Life Policy says an end-of-sale date "is generally not applicable" to SolarWinds' date-based licences, so `eos` stays null. |
| `ga` | nothing (yet) | A release-history table states no release date. See "Open items" below. |

`milestone_provenance` appears nowhere: no date in this source is derived, and
none is inferred from a cadence, a version number, or the absence of a row.

## Evidence

Sources inspected 2026-09-26:

* `https://www.solarwinds.com/legal/end-of-life-policy` — the phase
  definitions. Verbatim: "Technical Support will be available until the End of
  Life (EOL) Date, which is typically one year after the EOS Date." And for the
  sale end: "For most of SolarWinds' Self-Hosted Software which incorporate a
  date-based license model, the EOS date is generally not applicable."
* `https://documentation.solarwinds.com/en/success_center/ncm/content/release_notes/release_history.htm`
  (saved as `tests/fixtures/solarwinds-ncm.htm`) — the table shape every family
  page shares, with both non-milestone columns in the vendor's own words.
* Every other family page saved under `tests/fixtures/solarwinds-*.htm`, which
  is where the header spellings in `HISTORY_HEADERS` come from: the typo'd
  "EoL annoucement" on the Database Mapper and Task Factory pages, the plural
  capitals on IPAM, and the ordinary "EoL announcement" everywhere else. All
  three are real pages, so all three are in the reviewed vocabulary; anything
  else refuses the page.

## The negative case the tests pin

`tests/test_solarwinds.py::MappingTests` asserts, across every family the
sitemap publishes, that `eos` and `eossec` are null on every release while the
engineering-end cell is a stated date in more than a hundred of them. A
mapping that quietly filled `eossec` from `EoE effective date` would fail that
test on the first family.

## Open items this decision does not settle

* **`ga` coverage** (issue #119). The per-version release notes state
  "Release date: <day>" (DPA 2026.2: June 30, 2026; SolarWinds Platform 2026.2:
  June 9, 2026). Enumerating those pages is its own task; until then `ga` is
  null and the report says so.
* **The retired-products table** (issue #118). `support.solarwinds.com`
  publishes a 20-row cross-product table of retired products with the same
  EoE/EoL columns. Its host answers every request from a non-browser client
  with HTTP 403 — including `robots.txt` — so it cannot be refreshed
  deterministically from this collector. The table's own column notes confirm
  the mapping used here, and the blocked host is recorded as a no-go with that
  evidence. Nothing from that table is published, and no code pretends to read
  it.
* **Grouped version rows** ("4.1.1, 4.1.2", "12.1 and earlier",
  "2020.1 - 2023.1"). One vendor row states the dates of several releases;
  expanding it would attach a date to a release SolarWinds states it
  individually for none. They are excluded and named in the report.
