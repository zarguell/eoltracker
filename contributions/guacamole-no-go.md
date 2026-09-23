# Apache Guacamole — lifecycle investigation: NO-GO

Disposition for the Apache Guacamole lifecycle investigation. Recorded
2026-09-23. Scope: the Guacamole release bundle and its `guacamole-client` and
`guacamole-server` subprojects; no separate lifecycle is inferred for either
component.

## Decision

**NO-GO for a dated lifecycle record.** Apache Guacamole's official pages publish
release dates and label releases as current or archived, but none of the checked
primary sources publishes a version-specific EOL, EOS, or end-of-security-support
date, an explicit support duration, or a dated terminal trigger. A GA-only
release inventory would not add lifecycle coverage, so no product record or
derived milestone is justified.

Tier under AGENTS.md rule 8: (a) deterministic — fails, there is no lifecycle
table or API; (b) researched — fails, the official sources state no terminal date
or derivation rule; (c) absent — stands.

## Primary-source evidence

All linked pages were fetched on 2026-09-23.

| Source | Evidence | Lifecycle finding |
| --- | --- | --- |
| [Official homepage](https://guacamole.apache.org/) | “Download Apache Guacamole 1.6.0 Released on 2025-06-22”; “Community support for Apache Guacamole is available through the project's public mailing lists. Dedicated commercial support is also available through third party companies.” | Identifies the current release and support channels, but gives no dated entitlement or terminal milestone. |
| [Release archive](https://guacamole.apache.org/releases/) | “Each release below is listed by the version of the overall software bundle and the date on which it was released.” It labels 1.6.0 “Current Release” and 1.5.5 through 0.9.14 “Archived Releases.” | The dates are GA dates. “Current” and “Archived” are inventory labels; the archive does not define either as EOL or state when support ended. |
| [Current release/download page, 1.6.0](https://guacamole.apache.org/releases/1.6.0/) | Lists `guacamole-client` and `guacamole-server` source archives, the WAR, extensions, signatures, and checksums. “The 1.6.0 release is compatible with older 1.x components.” | This is the download and compatibility page linked from the homepage. Compatibility and upgrade advice are not support or lifecycle dates. |
| [Archived release page, 1.5.5](https://guacamole.apache.org/releases/1.5.5/) | “Apache Guacamole 1.5.5 is an archived release, and was originally released on 2024-04-05. The latest release of Apache Guacamole is 1.6.0.” | Confirms archive status and GA date only; it supplies no terminal date or support end. |
| [Support page](https://guacamole.apache.org/support/) | “the primary means for [support] ... [is] the project mailing lists”; “Companies providing support for Apache Guacamole are not endorsed nor vetted by the Apache Software Foundation.” | Describes community and third-party commercial support channels, not a version matrix, duration, or lifecycle. |

There is no separate official `/download/` page: that URL returns HTTP 404, and
the homepage's download link resolves to the current 1.6.0 release/download
page above.

## Current and archived inventory

The archive's current row is **1.6.0 — 2025-06-22**. Its archived rows are:

- 1.5.5 — 2024-04-05; 1.5.4 — 2023-12-07; 1.5.3 — 2023-07-31;
  1.5.2 — 2023-05-25; 1.5.1 — 2023-04-13; 1.5.0 — 2023-02-18;
  1.4.0 — 2022-01-01; 1.3.0 — 2021-01-01; 1.2.0 — 2020-06-28;
  1.1.0 — 2020-01-29; 1.0.0 — 2019-01-08; 0.9.14 — 2018-01-18.

The same page separately classifies 0.9.13-incubating through 0.9.10-incubating
as incubator releases and 0.9.9 through 0.8.3 as pre-Apache releases. These
status classes and all displayed dates are release inventory, not EOL evidence.

## Reconsideration criteria

Reconsider only when an authoritative Apache Guacamole source states either:

1. a dated EOL, EOS, or security-support end for a named release or component; or
2. an explicit support duration or dated release trigger whose base and rule can
   be retained with exact provenance, without using release cadence, release age,
   current support, archive status, or a newer release as a substitute.

Until then, Apache Guacamole remains absent from lifecycle coverage. Its official
release archive remains the source for GA dates and current/archive status.
