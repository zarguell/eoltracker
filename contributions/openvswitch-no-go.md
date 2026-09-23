# Open vSwitch — lifecycle investigation: NO-GO

Disposition for the Open vSwitch lifecycle investigation. Recorded 2026-09-23.
Scope: the Open vSwitch release series, with particular attention to the former
LTS 3.3.x series and the current 3.7.x LTS. This decision does not assign a
terminal date to ordinary, non-LTS releases or to a particular patch release.

## Decision

**NO-GO for a dated lifecycle record.** Open vSwitch publishes a current LTS
series, an LTS transition policy, release history, and security activity, but
none of the checked official sources publishes a version-specific EOL or
end-of-security-support date for 3.3.x. Its transition notice says only
“supported until the next release in February”; it neither names that release
nor supplies a year or day. The approximately twice-yearly release cadence
cannot supply the missing date.

Tier under AGENTS.md rule 8: (a) deterministic — fails, there is no lifecycle
table or product API; (b) researched — fails, the official sources provide no
terminal date and no sufficiently precise derivation rule; (c) absent — stands.

## Primary-source evidence

All linked pages were fetched on 2026-09-23. The excerpts below follow the
source order used for the decision.

| Source | Exact primary-source excerpt | Finding |
| --- | --- | --- |
| [Official release FAQ](https://docs.openvswitch.org/en/latest/faq/releases/) | “All official releases have been through a comprehensive testing process and are suitable for production use. Planned releases occur twice a year. If a significant bug is identified in an LTS release, we will provide an updated release that includes the fix. Releases that are not LTS may not be fixed and may just be supplanted by the next major release. The current LTS release is 3.7.x.” | Identifies 3.7.x as the current LTS and distinguishes LTS maintenance from ordinary releases. “Twice a year” is release cadence, not an EOL rule. |
| [Official release process](https://docs.openvswitch.org/en/latest/internals/release-process) | “At most three release branches are formally maintained at any given time: the latest release, the latest release designed as LTS and a previous LTS release during the transition period. An LTS release is one that the OVS project has designated as being maintained for a longer period of time. Currently, an LTS release is maintained until the next major release after the new LTS is chosen. This one release time frame is a transition period which is intended for users to upgrade from old LTS to new one.” “New LTS release is chosen every 2 years. The process is that current latest stable release becomes an LTS release at the same time the next major release is out.” “Open vSwitch makes releases at the following six-month cadence. All dates are approximate” | Defines the LTS handover and separate two-year LTS-designation cadence. The release table and schedule are explicitly approximate; they do not state 3.3.x's terminal date. |
| [Official security process](https://docs.openvswitch.org/en/latest/internals/security) | “When the patch is applied to LTS (long-term support) branches, a new version should be released.” | Requires security patches on LTS branches to result in a new version. It supplies no support duration or terminal milestone. |
| [Official 3.3.9 release announcement](https://mail.openvswitch.org/pipermail/ovs-announce/2026-March/000392.html) | “Current LTS series: <https://www.openvswitch.org/releases/openvswitch-3.3.9.tar.gz>” | Establishes the point-in-time 3.3.x LTS status and GA evidence, not a lifecycle end. |
| [Official security advisory](https://mail.openvswitch.org/pipermail/ovs-announce/2026-March/000393.html) | “Patches to fix this vulnerability in Open vSwitch 3.3 and newer are applied to the appropriate branches” and recommends upgrade to a known patched version including “3.3.9.” | Confirms a 3.3.x security fix, not when full or security support ends. |
| [Official 4.0.0 release announcement](https://mail.openvswitch.org/pipermail/ovs-announce/2026-August/000400.html) | “Also, with the release of OVS 4.0, the 3.7.x series becomes our new LTS series. The old LTS series 3.3.x will be supported until the next release in February.” | This is the 3.3.x transition boundary. It is not precise enough to publish a terminal date: the referenced release, year, and day are absent, and the general release dates are approximate. |
| [Official support page](https://www.openvswitch.org/support/) | “Open vSwitch can operate both as a soft switch running within the hypervisor, and as the control stack for switching silicon.” | Describes the software and supported platforms, but gives no EOL calendar or version-specific terminal date. |

## Scope and transition analysis

The LTS policy and the ordinary release schedule are separate:

- 3.7.x is the current LTS under both the release FAQ and the 4.0.0
  announcement.
- 3.3.x is the previous LTS in its transition period under the release-process
  policy. The 4.0.0 announcement says it remains supported “until the next
  release in February.”
- Ordinary releases are produced on an approximately six-month cadence. LTS
  fixes and security patches are maintenance behavior, not a stated three-year
  or other fixed support duration.
- The release-process example that 3.4 made “3.3 stable ⟶ new LTS” establishes
  an LTS designation transition, not the end of 3.3 support.

No terminal lifecycle date can therefore be stored without inference. In
particular, February 15, February 2027, and any exact end-of-month value are
not vendor-stated: the schedule says its dates are approximate, and the
transition sentence supplies neither the year nor a named triggering release.

## Why the old three-year wording is not used

The checked current FAQ, release-process policy, security process, support
page, and 4.0.0 transition announcement contain no “three-year” or “3-year”
support-window wording. A former or informal statement of that length is not
an exact terminal-date source: it has no current primary-source quote tying it
to 3.3.x or another named series, and a fixed duration would still require a
valid vendor-defined base date and rule. The present evidence supports an LTS
transition policy, not a universal three-year lifecycle.

## Why activity and fixes are not EOL evidence

A maintained branch, a new patch, and a security advisory demonstrate that
maintenance occurred; they do not identify when full or security support ends.
The official security process says patched LTS branches should receive a new
version, and the March 2026 advisory/work included fixes for 3.3.9. Likewise,
later branch activity would only show continuing work. Neither fact supplies a
terminal event, support-end date, or derivation rule. Conversely, the fact that
3.3.9 is retained in the release or download archive does not grant a new
support entitlement.

## Reopen condition

Reconsider only when an authoritative Open vSwitch source states either:

1. a dated EOL or end-of-security-support event for a named release series or
   release; or
2. an explicit dated release trigger whose named triggering release, base date,
   rule, and resulting lifecycle event are all stated precisely enough to retain
   with exact provenance.

A future official statement that 3.3.9 is the final 3.3 release, or a dated
support-end table, would satisfy the first condition. Until then, Open vSwitch
remains absent from dated lifecycle coverage; its official pages remain sources
for current release identity, LTS status, GA history, and maintenance notices.
