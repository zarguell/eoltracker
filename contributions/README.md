# Contributions

One-time researched lifecycle records: products with **no deterministic source**
— no API, no lifecycle table, only a vendor notice that states a date in prose.
AGENTS.md rule 8 tier (b). A contribution is admitted only when the exact vendor
sentence is stored here verbatim beside the date it proves, so every published
date can be re-read at the page it came from.

A contribution is never a substitute for a pipeline. It may not overwrite,
shadow or extend a record a deterministic collector owns, and it may not be used
for a product a collector could cover (rule 8 tier (a) — extend that pipeline
instead). Unknown dates stay unknown; a contribution never fills them in.

## Contributing

Put one JSON file per product in this directory and run:

```bash
.venv/bin/python -m engine contribute --check             # validate every file here
.venv/bin/python -m engine contribute --check my-product.json
.venv/bin/python -m engine contribute --install my-product.json
.venv/bin/python -m engine contribute --allow-stale-evidence --install my-product.json
```

`--check` is the default and writes nothing. `--install` writes the record into
`data/` and appends one `{id, action, at}` entry to
`data/contributions-log.json`; re-installing unchanged content is a no-op, so a
second run is byte-identical. `--allow-stale-evidence` is the offline path for
CI or a machine with no network: it accepts the stored evidence without
refetching the source and leaves `provenance.research.verified_at` null so the
difference stays visible on the record and on the site.

With no file named, every `contributions/*.json` is processed — so an unfinished
draft belongs in `contributions/drafts/`, which is gitignored and never read.
Files that pass review are committed here as the record of where the date came
from.

Both writes are gated by the catalog validation (`python -m engine validate`):
a contribution that would break the catalog is rolled back and never logged.

## Format

```json
{
  "target": "software",
  "id": "researched-synology-dsm-6-2",
  "name": "Synology DSM 6.2",
  "vendor": "Synology",
  "category": "os",
  "release": "6.2",
  "summary": "DiskStation Manager 6.2 for Synology NAS devices",
  "identifiers": [{"type": "purl", "id": "pkg:generic/synology-dsm@6.2"}],
  "links": {"about": "https://www.synology.com/en-global/dsm/6.2"},
  "milestones": {"eol": "2024-10-01"},
  "evidence": [
    {
      "quote": "DSM 6.2 will reach the end of the Extended Life Phase on October 1, 2024. After which, DSM 6.2 and related packages or applications will no longer receive functionality, security, and package updates.",
      "source_url": "https://www.synology.com/en-ca/products/status/eol-dsm62",
      "retrieved_at": "2026-09-17"
    }
  ],
  "contributor": "zarguell",
  "method": "manual",
  "stale_after": "2027-10-01",
  "notes": "Synology publishes no machine-readable lifecycle data."
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `target` | yes | `software` or `hardware` — decides the record shape and the schema. |
| `id` | no | Record id; defaults to `researched-` + the slug of `name`. Must be a lower-case hyphen slug and must keep the `researched-` prefix: researched records never share the id namespace a collector may claim later. |
| `name` | yes | Published product name. |
| `milestones` | yes | Non-empty subset of `ga`, `eos`, `eossec`, `eol`; each date is an ISO day (`YYYY-MM-DD`). |
| `evidence` | yes | The stored quotes, each `{quote, source_url, retrieved_at}` plus optional `milestones` naming which dates that quote backs. |
| `contributor` | yes | Who found it. The record's verifier becomes `researched-<contributor-slug>`, so one contributor's record can never be replaced by another's. |
| `method` | no | `manual` (default) or `agent`. |
| `stale_after` | no | Explicit review deadline. Absent, the record goes stale 180 days after it was last verified. |
| `notes` | no | Review context, kept on the record. |
| `vendor`, `category` | yes | `vendor` for hardware (and `product_line`, defaulting to `vendor`); `category` is one of the endoflife.date categories and `release` labels the release, both software-only. `release` defaults to the id without its `researched-` prefix. |
| `identifiers`, `links` | no | Software-only. `links` is either a mapping of labels to URLs or a list of `{rel, href}` pairs, as in the example. |

Milestones live in the same four keys as the rest of the catalog, with the same
semantics: `ga` general availability, `eos` end of sale, `eossec` end of
security support, `eol` the terminal date. A generic "support ends" date never
fills `eossec`, and a date is quoted verbatim before it is stored — never
inferred from a release cadence, a newer release, or an upstream flag.

## What gets checked

Both checks run before anything is written:

1. **The date is in the quote.** Every stored milestone date must appear in the
   quote stored beside it, at day precision (`October 1, 2024`, `Oct 1 2024` and
   `2024-10-01` are accepted; `October 2024` is not evidence for a day).
2. **The quote is in the source.** The quote must appear in the text fetched
   from its `source_url` at validation time — tags stripped, entities decoded,
   whitespace folded, sentence order and wording unchanged. `--allow-stale-evidence`
   skips this fetch and is recorded as unverified.
3. **The id is safe and namespaced**, the record matches `schema/product.json` or
   `schema/hardware.json`, and the file being written — if it exists — carries
   this contributor's own verifier. A deterministic record is refused outright.

The published record carries the research provenance for display:

```json
"provenance": {
  "source_url": "https://www.synology.com/en-ca/products/status/eol-dsm62",
  "verifier": "researched-zarguell",
  "last_checked": "2026-09-17T12:00:00Z",
  "upstream_modified": null,
  "research": {
    "quote": "...verbatim...",
    "source_url": "https://www.synology.com/en-ca/products/status/eol-dsm62",
    "retrieved_at": "2026-09-17",
    "contributor": "zarguell",
    "method": "manual",
    "verified_at": "2026-09-17T12:00:00Z",
    "stale_after": null,
    "evidence": [{"quote": "...verbatim...", "source_url": "...", "retrieved_at": "2026-09-17"}]
  }
}
```

plus `upstream.Contribution` — `{"text": <quote>, "value": null, "datetime": null,
"role": null, "links": [<source urls>]}` — on the release (software) or the record
(hardware), so the raw contribution is republished alongside the normalized dates
the way every other record republishes its upstream cells.

`python -m engine validate` re-derives all of this offline from the stored quotes,
so a hand-edited record that no longer matches its own evidence fails the gate.

## Review

A researched record states a fact that no pipeline can re-derive, so it needs to
be re-read: the site flags a record whose evidence has not been refetched for 180
days (or past `stale_after`). To refresh, re-fetch the source page, confirm the
sentence is still published, update `evidence[].retrieved_at`, and reinstall.
