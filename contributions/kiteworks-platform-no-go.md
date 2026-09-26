# Kiteworks platform — lifecycle investigation: NO-GO

Disposition for the current Kiteworks platform lifecycle investigation (#124).
Recorded 2026-09-26. Scope: the Kiteworks platform release train and its named
components — Kiteworks Core, Kiteworks Email Protection Gateway (EPG),
Kiteworks Secure Data Forms (SDF), and Kiteworks Secure MFT Server/Client. The
retired Accellion FTA predecessor is covered separately by
`contributions/kiteworks-accellion-fta.json`; the Kiteworks subsidiary brands
are scoped in `contributions/kiteworks-subsidiaries-scope.md`.

## Decision

**NO-GO for a dated lifecycle record.** Kiteworks publishes no version support
matrix, no release lifecycle table and no machine-readable lifecycle feed for
any current product. Support is tied to each customer's contractual License
Term, not to a version; the release notices that exist announce general
availability without a day; the customer portal that would hold a version or
support statement is login-gated; and the platform's only machine-readable feed
carries version-to-version fix ranges, which are inventory and patch facts, not
support entitlement.

Tier under AGENTS.md rule 8: (a) deterministic — fails, there is no lifecycle
table, dated API or support matrix; (b) researched — fails, no primary source
states a terminal date, an explicit support duration, or a dated release trigger
for any named release; (c) absent — stands.

## Primary-source evidence

All sources were checked on 2026-09-26. Each row states its access shape, because
the shape is what decides the tier.

| Source | Access shape | What it states | Why it is not lifecycle coverage |
| --- | --- | --- | --- |
| [Maintenance Support Policy — Enterprise](https://www.kiteworks.com/legal/maintenance-support-policy-enterprise/) | public static HTML, `article:modified_time` 2025-01-10 | "Kiteworks Maintenance Support Policy applies solely with respect to the Kiteworks Software." Section D) Updates: "Kiteworks shall provide Licensee with Updates to the Kiteworks Software, on a reasonable, periodic basis, as such are provided by Kiteworks to its Licensee base generally." | Support is scoped to the licensee, not to a version; "reasonable, periodic basis" states no duration, no version scope and no end date, so it yields no derivable milestone. |
| [Kiteworks Solution License Agreement 19.3](https://www.kiteworks.com/legal/ksla/) | public static HTML, `article:modified_time` 2026-03-31 | Section 5: Kiteworks provides "Maintenance Support Services for the License Term". "License Term" means "the subscription period for use of the Kiteworks Solution, as identified on the applicable Order. Each renewal is a separate License Term." | Entitlement is per-subscription and per-customer; it never names a version, so no version EOL can be derived from it. |
| [Technical Support and Services](https://www.kiteworks.com/support/) | public static HTML, `article:modified_time` 2026-08-10 | Knowledge base and product updates are offered "exclusively to Kiteworks clients"; the only actionable control is "LOG IN TO THE SUPPORT PORTAL". | Points at the gated portal; publishes no release or support statement itself. |
| [Kiteworks community/support portal](https://community.kiteworks.com/aspx/GuestHome?usertype=customer) | **login-gated** — guest view returns a script-rendered shell with no article body | — | Where release notes, a supported-version list and the knowledge base actually live; rule: never scrape behind a login. Recorded as a blocker, not as proof of absence. |
| [API changelog](https://developer.kiteworks.com/changelog.html) | vendor docs, served as markdown (alternate) | API versions v18–v28 with a breaking/warning change summary and endpoints annotated "Last Present In v4.1 / v5.1 / v6 / v7 / v9". | API-contract versions, dateless. An API version is not a platform release, and "last present in v9" is an interface change, not a support end. |
| [Upgrade to API Version 28](https://developer.kiteworks.com/upgrade-api-v28.html) | vendor docs, markdown | "Kiteworks API v28 is the current and final supported version." | A statement about an interface contract with no date attached; it cannot become a platform lifecycle milestone. |
| [Kiteworks security advisories API](https://api.github.com/repos/kiteworks/security-advisories/security-advisories?per_page=100) | **machine-readable JSON**, public repo, no auth | 23 advisories with per-component `vulnerable_version_range` and `patched_versions` (e.g. Core `<9.2.0` → `9.2.0`; EPG `<9.2.1` → `9.2.1`; SDF `<9.3.0` → `9.3.0`) plus `published_at` disclosure dates. | A `<9.2.0` range names no release date and no support end, and an advisory publication date is a disclosure date, not a milestone. Inspected and rejected as a lifecycle source. |
| [Precautionary shutdown advisory](https://www.kiteworks.com/company/press-releases/kiteworks-precautionary-shutdown-advisory/) | public static HTML, 2026-09-25 | "Kiteworks has accounted for all known vulnerabilities in our current release, 9.5.1, and we continue to recommend customers run the latest version." | Identifies the current version on one date — a status fact, not a GA or lifecycle date. |
| [Kiteworks 7.7 What's New](https://www.kiteworks.com/sites/default/files/resources/sp/Kiteworks_7.7_Whats_New_Customer_Notice_Winter_2022.pdf) | public PDF | "Version 7.7 of Kiteworks is now generally available." | A GA claim with no day anywhere in the document and no support-end statement. The "Winter 2022" in the filename is the document's period, not a stated release day. |
| [Kiteworks 7.10 What's New](https://www.kiteworks.com/sites/default/files/resources/sp/Kiteworks_7.10_Whats_New_Customer_Notice_FINAL_2023-01-18.pdf) | public PDF | "Kiteworks is pleased to announce that release 7.10 is now generally available." | Same: no day, no support end. The filename's 2023-01-18 is a document date only. |
| [Kiteworks 8.0 What's Coming](https://www.kiteworks.com/sites/default/files/resources/sp/Kiteworks_8.0_Whats_New_Customer_Notice_2023-04-04%20Rushmore.pdf) | public PDF | "Kiteworks plans to make the Kiteworks 8.0 release available in April." Legacy Admin switch available "until 2024". | A forward-looking, month-only plan — not a GA statement — and the only date is a year-only **feature** deprecation, not a product lifecycle. |
| [Drummond AS2 certification release](https://www.kiteworks.com/company/press-releases/kiteworks-drummond-as2-certification-secure-mft-server/) | public static HTML, 2026-06-17 | "Kiteworks Secure MFT Server v9.4 is listed by Drummond Group as an AS2 certified product." | Names the separately versioned MFT component and one version, with no date attached to it. |
| [docs.kiteworks.com](https://docs.kiteworks.com/) | **does not resolve** (ENOTFOUND) | — | No alternate documentation host exists at this name, so no machine-readable release index is available there. |

## Why the machine-readable feed was inspected and rejected

The advisories API is the only Kiteworks-controlled, unauthenticated,
machine-readable endpoint found. It is deterministic to fetch, which makes it
tempting as a tier-(a) source — but its fields model *fix ranges*: which versions
existed and which were patched. Mapping them to lifecycle would publish
"patched in 9.2.0" as if it were "supported through 9.2.0". AGENTS.md rule 2
forbids exactly that inference, and rule 7 forbids presenting inventory as
support entitlement. A version that stops appearing in advisories is not EOL,
and an advisory's `published_at` is its disclosure date, not a milestone.

## Why the release notices yield no milestone

The three public release notices state availability but never a day:

- 7.7 and 7.10 announce general availability with no day, so no `ga` day can be
  published (AGENTS.md rule 2: no fabricated dates).
- 8.0 is a plan — "plans to make ... available in April" — and month-only, so it
  is not a GA statement and cannot be padded to a day (rule 4).
- The "until 2024" note is a year-only **feature** deprecation for the Legacy
  Admin console switch, not a release lifecycle date, and cannot populate any
  milestone.

## Why support status is not product EOL

The Maintenance Support Policy and the KSLA both tie support to the customer's
License Term and to a reasonable periodic update cadence. Neither names a
version, a support window, a duration or a terminal trigger. The current-release
statement ("our current release, 9.5.1") describes one version on one day.
None of these can be converted into a named release's EOL, and no
`milestone_provenance`-eligible duration or trigger exists.

## Reopen condition

Reopen only when Kiteworks publishes a **public**, version-scoped statement that
provides one of:

1. a dated EOL, EOS, or end-of-security-support date for a named release or
   component; or
2. an explicit support duration or dated release trigger whose base and rule can
   be stored with exact provenance — at which point a `milestone_provenance`
   derivation, not a vendor-stated date, is the honest result; or
3. a publicly reachable release/support matrix (for example, if the customer
   portal exposes an unauthenticated release index, or the vendor republishes
   one on `kiteworks.com` or `developer.kiteworks.com`).

Until then the platform remains absent rather than receiving a fabricated EOL.
No `data/` record is added, and no `engine/sources.py` registration is
warranted.

## What must not be done

Do not derive Kiteworks EOL from the "reasonable, periodic basis" update
cadence, from the absence of a version in the advisories feed, from an advisory
`published_at`, from the 8.0 "until 2024" Legacy Admin note, or from a
customer's License Term. Do not treat an API version (v18–v28) as a platform
release. Do not attach a GA date to 7.7 or 7.10 from a PDF filename, or to 8.0
from "available in April". Do not scrape the login-gated support portal.
