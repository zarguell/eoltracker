# CISA BOD 26-02 and the "EOS Edge Device List" — investigation and no-go

Recorded 2026-09-26. Question asked: does CISA publish, or is it building, a
machine-readable feed of end-of-support edge devices under Binding Operational
Directive 26-02 that this catalog could ingest?

**Answer: the directive mandates such a list, with exactly the three fields a
release row needs, and the list is not published anywhere. There is no feed to
ingest today.**

## The directive

`https://www.cisa.gov/news-events/directives/bod-26-02-mitigating-risk-end-support-edge-devices`
— "BOD 26-02: Mitigating Risk From End-of-Support Edge Devices", issued by CISA
alone on **February 05, 2026**, in coordination with OMB. (The companion fact
sheet is tri-agency — CISA, FBI and the UK NCSC — but that is a recommendation
document, not the directive.)

It binds **Federal Civilian Executive Branch agencies only**. The press release
is explicit that it reaches the private sector by encouragement, not obligation:
"CISA strongly encourages non-federal organizations to adopt similar actions."
Vendors are never addressed.

Its definition of the concept, verbatim:

> **End of Support:** Hardware devices, firmware, and software versions that no
> longer receive timely, supported updates from the original equipment
> manufacturer, including patches for CVEs, security updates, software fixes
> (hotfixes), and defects.

Note what is *not* in the directive: the words "end of life" and "end of sale"
appear nowhere in it. Only "end of support" is defined, and it is keyed to
**update behaviour**, not to a commercial milestone or a published date.

## The list exists on paper, and nowhere else

CISA Action #1, verbatim:

> CISA will provide an initial list of EOS and soon-to-be EOS edge devices for
> Required Actions #2 and #3. This list will include the IT product name,
> version number, and end of support date.

Those three fields are precisely what a release row in this catalog carries. The
problem is everything around that sentence:

1. **The directive contains no publication requirement of any kind.** Every data
   obligation in it runs *agency → CISA*: "provide this inventory to CISA using
   the CISA-provided template", "Report these decommissions to CISA". The verb is
   always *provide* or *report to CISA*; never publish, post, or disclose. CISA's
   own action is to *provide* the list "for Required Actions #2 and #3" — a
   bounded audience of agencies performing two specific actions.
2. **The directive does not link the list.** The string "EOS Edge Device List"
   appears in the governing document as plain text with no anchor, no
   attachment, and no path. There is not even a PDF of the directive itself.
3. **The "CISA-provided template" is likewise unpublished**, as is every
   CISA-provided reporting template the directive names.
4. **CISA describes the list as a starting point that goes stale on purpose.**
   Required Action #2's own annotation: "The CISA EOS Edge Device List is a
   preliminary repository of EOS devices. This list is to facilitate each agency's
   identification of specific devices within the first three months after issuance
   of this Directive. After the first three months, agencies are responsible for
   continuing to identify, track, and refresh all edge devices within the
   agency's infrastructure."

Point 4 matters for a catalog: even as published to agencies, this is explicitly
a three-month bootstrap, not a maintained feed. A daily refresh job pointed at it
would be pointed at something the directive itself says to stop trusting.

## Where it was looked for, and what came back

| Where | Result |
| --- | --- |
| `cisa.gov/sitemap.xml` → `default/sitemap.xml` and `documents/sitemap.xml`, both complete | No page and no file for the list. The only 2026-02 document is the joint fact sheet. |
| CISA site search for the exact phrase "EOS Edge Device List" | Zero results |
| `github.com/orgs/cisagov/repositories?q=eos`, and an org-wide API search for `eol OR eos OR end-of-life OR lifecycle` | 0 repositories |
| `/sites/default/files/feeds/` (CISA's own anonymous-feed pattern, where KEV lives) | Only `known_exploited_vulnerabilities.json` and its schema |
| `/sites/default/files/csv/` | Only the KEV CSV |
| 14 plausible CISA-hosted paths for the list or a template (`.csv`, `.json`, `.xlsx`, page slugs) | All 404 |
| `api.cisa.gov` | Does not resolve (NXDOMAIN) — CISA has no public API host |
| The joint fact sheet PDF and the Edge Device Security topic page | Both recommend building *your own* inventory ("Create and maintain an asset inventory that captures all edge devices and their EOS dates") and point back at the directive |

## What CISA does publish, and why none of it qualifies

| Artifact | Status | Carries EOL/EOS dates? |
| --- | --- | --- |
| KEV catalog (`.../feeds/known_exploited_vulnerabilities.json`) | 200, `application/json`, no auth, 1,726 records, CC0 1.0 | **No.** Its twelve fields are `cveID, vendorProject, product, vulnerabilityName, dateAdded, shortDescription, requiredAction, dueDate, knownRansomwareCampaignUse, forensicTriage, notes, cwes`. There is no version and no lifecycle field. |
| KEV CSV + published JSON Schema | 200 | Same twelve columns; the schema has no lifecycle property to populate |
| CSAF 2.0 advisory feeds (IT/OT/VA, PGP-signed, `cisagov/CSAF`) | 200, real documents read in full | **Schema yes, data no.** CSAF *can* express `product_version.status = end_of_life`, but CISA does not populate it. A `product_version_range` like `>=2011.4074|<2026.1` is a version range, not a lifecycle date. |
| Vulnrichment (`cisagov/vulnrichment`) | 200 | CVE-keyed enrichment; no lifecycle concept |
| ICS advisories | 200 | Operational Technology, which the directive explicitly excludes from its own scope |

One trap worth naming, because a future parser would hit it: some KEV
`shortDescription` values for Linux kernel branches end with the free text "The
impacted product(s) could be end-of-life (EoL) and/or end-of-service (EoS).
Users are advised to discontinue use and/or transition to a supported version."
That is hedged, dateless, and about kernel release branches. A collector that
grepped KEV for "end-of-life" would harvest a handful of Linux rows and mistake
them for a lifecycle feed. KEV must be rejected explicitly, not pattern-matched.

## The provenance question, which is the real blocker

The directive's scope test is disjunctive, and this is the load-bearing clause:

> Is considered by its vendor **or CISA** to be EOS, and,

So CISA's own determination is explicitly contemplated — a device can be in
scope on CISA's judgement alone, with no vendor-published date. But the
directive **never states where the dates in the list come from**: not that they
are vendor-published, not that CISA verified them, not that they are estimates.
The provenance of a given end-of-support date is undefined in the instrument.

That is a materially different kind of evidence from everything else in this
catalog, and the difference is not cosmetic:

* A vendor-primary record says "this vendor published this date, here is the
  column it came from", and validation re-derives every milestone from the
  stored cells.
* A CISA list would say "CISA determined this device is end of support on this
  date" — closer in kind to the community catalog this repository already ingests
  as a *registered source with attribution*, and further from a vendor notice.

If the list is ever published, ingesting it honestly means: a distinct verifier,
attribution that says the determination is CISA's rather than a vendor's, the
"end of support date" field named as the label a milestone was read from, and —
per this repository's rule that two sources disagreeing about one date is a
review and never a silent merge — **every row that overlaps an existing
vendor-sourced record reported as an exclusion rather than merged.**

## Why that overlap would be large, and where the real gap is

The edge-device vendors the joint fact sheet names as actively exploited are
load balancers, firewalls, routers and VPN gateways. Against this catalog's
6,999 hardware records:

| Vendor | Records | With an `eol` date |
| --- | --- | --- |
| Juniper Networks | 3,499 | 3,114 |
| Cisco | 772 | 666 |
| Fortinet, Palo Alto Networks, Ivanti, F5, SonicWall, MikroTik, Citrix, Barracuda, Check Point, Sophos, WatchGuard, Aruba/Meraki, Netgear, Extreme, Forcepoint | **0** | 0 |

So a CISA list would split two ways. Against Juniper and Cisco it would mostly
**conflict** with dates this catalog already holds from the vendors themselves.
Against the fifteen absent vendors it would be the only source available — and
for those, a CISA determination would be a tier-(b) researched record at best, not
a vendor-primary one, unless each row carries a citation to the vendor's own
notice.

That second group is the genuine coverage gap, and it is worth pursuing through
the vendors' own lifecycle pages (the same route that produced the SolarWinds
and Progress collectors), not through a government determination of who is
unsupported.

## What would change this disposition

* CISA publishes the EOS Edge Device List as JSON, CSV or XLSX at a stable URL,
  **and** each row carries a citation to the vendor notice the date came from. With
  citations it is a legitimate registered source; without them it is a
  researched-record source at best.
* CISA issues the Supplemental Direction its Action #3 contemplates
  ("consider issuing Supplemental Direction"), which is the most likely vehicle
  for a published schema.
* A Supplemental Direction or a follow-on directive turns the list from a
  three-month bootstrap into a maintained feed, which is what a daily refresh job
  would need.

## One takeaway worth keeping regardless

CISA's definition is a citable, authoritative statement of something this
repository asserts in its own no-go records without a citation: **being
unsupported is a status, not the absence of a date.** A vendor that never
published an end-of-life date has not thereby stated that a product is
supported, and this catalog's treatment of a missing date — absent, never
inferred — is the same position CISA's directive takes.
