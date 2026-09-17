# UniFi Network Server — lifecycle investigation: NO-GO

Disposition for the self-hosted UniFi Network Server lifecycle investigation
(local issue #32). Recorded 2026-09-17. Scope: the **self-hosted Network Server
application** (the controller software Ubiquiti ships for Linux, Windows and
macOS) and its release line only. Ubiquiti's other control planes are separate
products and were not merged into this scope:

- **UniFi OS Server** — a distinct product with its own version line (5.x) and
  its own download entries; it is the *successor*, not another edition.
- **UniFi Network Application on UniFi OS / UniFi OS Native** — the console
  build of the same application, a different artifact and a different update
  channel.
- **UniFi Security Gateway hardware** — investigated separately (local issue
  #33, `contributions/unifi-security-gateway-no-go.md`).
- **UniFi Application Server (all models)** — a hardware appliance, not this
  software. It appears as `Legacy` on the vendor's Vintage/Legacy page; the
  Network Server software does not.

## Decision

**NO-GO for a dated lifecycle record.** Ubiquiti publishes release dates and a
rolling "run the latest" policy for the Network Server, and no per-version
end-of-life, end-of-support or end-of-sale date — no calendar end date at all.
No contribution file was written and no record was installed.

Tier under AGENTS.md rule 8:

- **(a) deterministic — fails for lifecycle.** The download listing behind
  `ui.com/download/releases/network-server` *is* a machine-readable feed
  (`https://download.svc.ui.com/v1/downloads?page=N`), but it carries release
  metadata only. It has no lifecycle field of any kind and cannot be a lifecycle
  source. See "What the feed does and does not state" below.
- **(b) researched — fails.** No authoritative primary source states an explicit
  end date for any Network Server version. The statements that exist are
  *relative* ("the new standard", "the legacy UniFi Network Server", "we
  recommend users upgrade"), which the contribution rules call evidence that no
  end date exists, never a date in itself.
- **(c) absent — stands.**

A GA-only record was considered and **rejected**, the same way the Docker
Desktop investigation rejected one: every `eol` would be null, so the record
would publish no lifecycle fact the vendor's own release list does not already
publish, while reading as lifecycle coverage in the catalog. The catalog has no
"supported version" list to publish here, only release dates.

## Sources checked (fetched live, 2026-09-17)

| Source | What it states | Why it is not lifecycle coverage |
| --- | --- | --- |
| `https://ui.com/download/releases/network-server` | The rendered download listing. For 10.6.106 it lists macOS, Windows and Debian/Ubuntu builds, "14 Sept 2026", `V10.6.106`, plus a "View Older Versions" link | A release list with day-precision dates. Its only quantitative statement is the availability notice quoted below — a **download-availability** statement, not a support end |
| `https://download.svc.ui.com/v1/downloads?page=N` (the JSON the page renders) | 3,694 rows across 37 pages, 28 fields, day-precision `date_published` from 2007-07-18 to 2026-09-17. 321 rows are Network Application/Controller entries spanning 2019-02-13 … 2026-09-15 | Release/publication metadata and artifacts only. **No** `eol`, `eos`, `eol_date`, `support_end`, `lifecycle` or `status` field exists on any row. Every one of the 3,694 rows has `enabled: true`, so the feed's own flag cannot signal even a withdrawn download |
| `https://help.ui.com/hc/en-us/articles/1500001268521-Ubiquiti-s-Vintage-and-Legacy-Products` | The vendor's own Vintage/Legacy list and its two status definitions | The **Network Server software is not listed at all.** The nearest entry, "UniFi Application Server (all models)", is hardware. The page carries no date anywhere: the 587-word article contains **no four-digit year**, no date-precision string and no month-year string |
| `https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi` (updated 2026-09-15) | Names UniFi OS Server as the new standard "replacing the legacy UniFi Network Server", and still documents installing the legacy server | Relative successor statement, no date. "Legacy" here is a description of the self-hosting path, not a dated milestone |
| `https://help.ui.com/hc/en-us/articles/360012282453-Self-Hosting-a-UniFi-Network-Server` (updated 2026-09-17) | Carries a banner pointing to UniFi OS Server | Recommendation only, no date |
| `https://community.ui.com/releases/r/network/10.6.106` (release notes, 2026-09-15) | Current release notes; the self-hosting note recommends UniFi OS Server going forward | Recommendation only. The release itself is three days old and the line is actively shipping |
| `https://community.ui.com/RELEASES` — full release corpus | 4,231 release posts enumerated. Exactly **one** has a lifecycle-shaped title ("USG-XG-8 Product Status Update", 2019-03-30), and it concerns a gateway SKU, not this software. Searches for "end of life", "end of support", "end of sale", "EOL", "discontinued", "obsoletion" return the same gateway post or unrelated results | No Network Server lifecycle announcement exists in the corpus |
| `https://help.ui.com/api/v2/help_center/articles/search.json` | Searches for "end of life", "EOL", "EOS", "end of sale", "discontinued", "product retirement", "obsoletion", "lifecycle", "no longer supported" — none returns a Network Server lifecycle article | No lifecycle article exists in the help center |
| `https://ui.com/sitemap.xml` | 81 URLs; no lifecycle, EOL or support-policy page | No vendor lifecycle page to read |
| `https://endoflife.date/api/all.json` | 483 product slugs; no UniFi/Ubiquiti slug | Confirms no upstream community record to extend |

## Verbatim evidence

Every sentence below was confirmed to appear in the live page text on
2026-09-17 (tags stripped, entities decoded, whitespace folded; where a
tag boundary split the source, the rendered punctuation is shown).

- `ui.com/download/releases/network-server`
  > Certain releases are no longer available due to security and/or regulatory requirements. We always recommend running the latest software to ensure optimal network performance and security. If you require an unlisted release, please contact Ubiquiti Support.
- `help.ui.com/…/34210126298775`
  > The UniFi OS Server is the new standard for self-hosting UniFi, replacing the legacy UniFi Network Server.
  > To install the legacy UniFi Network Server instead, refer to the appropriate guide below based on your operating system:
- `help.ui.com/…/360012282453`
  > The UniFi OS Server is the new standard for self-hosting UniFi, offering support for advanced features like Organizations, IdP Integration, and Site Magic SD-WAN.
- `community.ui.com/releases/r/network/10.6.106`
  > Going forward, we recommend users upgrade to UniFi OS Server for all self-hosted deployments.
- `help.ui.com/…/1500001268521` (the Vintage/Legacy definitions, for contrast with what is *not* claimed for this product)
  > Vintage Products - These products are no longer manufactured or actively developed but may still be available for purchase.
  > Legacy Products - These products have stopped receiving updates and are no longer distributed by Ubiquiti, though they may still be available from third-party sellers.

## Why the relative statements were not converted into dates

| Statement | Source | Why it is not a stored date |
| --- | --- | --- |
| "Certain releases are no longer available …" | download page | Download availability, not support end. It names no version and no date, and it is contradicted as a per-release signal by the feed, where all 3,694 rows read `enabled: true` |
| "replacing the legacy UniFi Network Server" | Self-Hosting UniFi | A successor relationship. Deriving an end date from it would invent a date Ubiquiti never published |
| "Going forward, we recommend users upgrade to UniFi OS Server" | 10.6.106 notes | A recommendation attached to a release shipped three days ago, while the product keeps shipping |
| "The UniFi OS Server is the new standard for self-hosting UniFi" | both self-hosting articles | Policy direction, the shape `contributions/README.md` calls evidence that no end date exists |

`contributions/README.md` states the rule directly: "A rolling support policy
('only the latest minor branch is maintained') is evidence that no end date
exists, never a date in itself." Ubiquiti's Network Server policy is that shape:
the newest release is the recommended one, and no version is given a deadline.

## What the feed does and does not state

Recorded because it is the reason tier (a) fails for *lifecycle* even though a
machine-readable release feed exists — and because a future reader may mistake
it for a date source.

- It states: `id`, `name`, `version`, `date_published`, `slug`, `category`,
  `file_path`/`file_url`, `filename`, `release_notes`/`release_notes_url`,
  `products`, `product_lines`, `enabled`, `featured`, and a few rarely populated
  fields (`build`, `mib`, `size`, `architecture`, `revision_history`). 3,689 of
  3,694 rows carry a day-precision `date_published`.
- It does **not** state: any end date, support tier, withdrawal date or
  lifecycle status. There is no such key on any row.
- A single application version appears as **five** rows — for example 10.6.106
  is rows for macOS, Windows, Debian/Ubuntu, UniFi OS and UniFi OS Native — so
  even a release-date record would need per-artifact reconciliation
  (321 rows collapse to 85 distinct version strings).
- The listing mixes release artifacts with documents: across all 3,694 rows the
  categories are `firmware` (2,647), `software` (394), `quick-start-guides`
  (299), `datasheets` (220), `installation-guides` (47), `user-guides` (25) and
  others. Release dates would have to be filtered from datasheets and case
  studies.

Reproduction note: the endpoint is undocumented, requires an `Origin` header,
and its CloudFront layer ignores the `page` parameter on a cache hit. Naive
sequential requests for pages 1–37 returned only 900 unique rows because pages
repeat; converging on the advertised 3,694 required retrying each page until the
response's own `pagination.page` matched the request. Any future use of this
endpoint must verify the echoed page number rather than trust the response.

## Source limitations

1. No per-version Network Server lifecycle or EOL table exists anywhere in
   Ubiquiti's documentation as of 2026-09-17, so there is no date to collect
   deterministically and no quote to store as a researched contribution.
2. The vendor's only lifecycle vocabulary for UniFi is the Vintage/Legacy page,
   which is a status list without dates — and it does not list this software.
3. The lifecycle shape Ubiquiti *does* publish elsewhere is a dated obsoletion
   announcement for a named hardware SKU (see the USG disposition for the
   worked example). No such notice has been published for the Network Server.
   This disposition is therefore **not** a claim that Ubiquiti never publishes
   dates; it is a record that none exists for this product.
4. The current release line is active: 10.6.106 shipped 2026-09-15, and 85
   distinct versions are listed from 2019-02-13 onward (55 of them under the
   "UniFi Network Application" name, the rest still under "UniFi Network
   Controller"). A product still shipping has no end date to publish, by
   definition.
5. Product identity is genuinely split. The coverage request names a single
   "UniFi Network Server", which in current Ubiquiti documentation covers at
   least three things (the legacy self-hosted server, the UniFi OS / UniFi OS
   Native application build, and the successor UniFi OS Server). Any future
   coverage would first have to fix which identity it tracks; a record that
   merged them would be wrong about all three.

## Reopen condition

Reopen when Ubiquiti publishes an authoritative, day-precision statement tying a
**named Network Server version or branch** to a lifecycle end — for example a
per-version lifecycle/EOL table under `ui.com/download` or `help.ui.com`, or a
release-post announcement of the obsoletion form the vendor already uses for
hardware ("… will no longer receive new system releases, critical bug fixes, or
security updates after \<date>"). At that point the date is a tier (b) researched
contribution, or tier (a) if the statement appears in a table a collector can
re-derive. Note that if a deterministic collector is ever built on
`download.svc.ui.com`, it must be justified as a *release-date* source, not a
lifecycle one, and it must handle the pagination cache behaviour above.

Until then the product stays absent, with release dates available from
Ubiquiti's own download page.

## No record published

No `unifi-network-server` contribution file and no entry under `data/products/`
were created. The catalog is unchanged by this investigation.
