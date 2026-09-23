# Jitsi Meet — lifecycle investigation: NO-GO

Disposition for the existing Jitsi Meet lifecycle investigation (#38), recorded
2026-09-23. Scope: the Jitsi open-source web/server bundle, Android and iOS
apps, and Android and iOS mobile SDKs. Docker/GHCR, Debian/Ubuntu packages,
meet.jit.si, and 8x8 Jitsi as a Service (JaaS) are separate distribution or
hosted-service scopes and are not collapsed into one Jitsi version.

## Decision

**NO-GO for a dated lifecycle record.** Jitsi's official release material
publishes release availability and change notes for three independently cycled
open-source groups, but the checked primary sources publish no per-version EOL,
end-of-security-support date, support duration, dated terminal trigger, or
support-inheritance rule. A release inventory alone would not add lifecycle
coverage, so no product record and no derived milestone are justified.

Tier under AGENTS.md rule 8: (a) deterministic — fails, because there is no
Jitsi lifecycle table or API; (b) researched — fails, because the official
sources supply neither a terminal date nor an explicit derivation rule; (c)
absent — stands.

## Primary-source evidence

All linked sources were checked on 2026-09-23. Quotes are presented in source
page order.

### 1. Official release-notes README: three separate release cycles

The [official release-notes README](https://github.com/jitsi/jitsi-meet-release-notes)
lists these groups in order:

1. **Web** — “These releases include the Jitsi Meet web frontend and the matching lib-jitsi-meet, jicofo and jitsi-videobridge.”
2. **Mobile apps** — “These releases include the Jitsi Meet mobile apps for Android and iOS.”
3. **Mobile SDKs** — “These releases include the Jitsi Meet mobile SDKs for Android and iOS.”

The same README describes these groups as having “different release cycles.”
That distinction is lifecycle-relevant: a web release date, app release date,
or SDK release date cannot be transferred to either of the other groups.

### 2. Release changelogs: publication dates, not support ends

The release-note repository publishes separate changelogs. Their current
entries, in displayed order, are:

- [Web changelog](https://raw.githubusercontent.com/jitsi/jitsi-meet-release-notes/master/CHANGELOG-WEB.md):
  `2.0.11248 (2026-09-14)`, `2.0.11146 (2026-08-03)`, then
  `2.0.11031 (2026-06-08)`. Each heading pairs the web release with matching
  `jitsi-meet`, `jicofo`, and `jitsi-videobridge` component releases.
- [Mobile-apps changelog](https://raw.githubusercontent.com/jitsi/jitsi-meet-release-notes/master/CHANGELOG-MOBILE-APPS.md):
  `26.2.0 (2026-07-01)`, then `26.1.1 (2026-05-08)`, `26.1.0 (2026-04-17)`,
  and `26.0.0 (2026-01-23)`.
- [Mobile-SDK changelog](https://raw.githubusercontent.com/jitsi/jitsi-meet-release-notes/master/CHANGELOG-MOBILE-SDKS.md):
  `13.1.1 (2026-08-06)`, then `13.0.0 (2026-07-09)` and
  `12.1.5 (2026-06-22)`.

These pages contain version headings, publication dates, and feature/fix
notes. Inspection of the complete changelogs found no EOL, supported-version,
security-support-window, or Jitsi-LTS policy. Their historical entries are
release history, not proof of when support ended.

The web changelog's reference to “Node 24, the current LTS” describes Node.js
dependency compatibility. It is neither a Jitsi release policy nor a Jitsi
support date, and Node's lifecycle must not be inherited by Jitsi.

### 3. Stable builds: tags and channels, not a terminal lifecycle

Jitsi's [2018 stable-build announcement](https://jitsi.org/blog/jitsi-meet-stable-releases-now-more-discoverable/)
distinguishes ordinary continuous-integration tags from selected stable
releases:

- “We make tags for every successful build our CI makes, and also every time we ‘cut a release’.”
- “We have started making special tags for stable releases. They look like `stable/jitsi_meet_XXX` across all projects.”

It points readers to the latest GitHub release for release highlights. It does
not define how long a stable build is supported or when one reaches EOL.

The [official release index](https://jitsi.github.io/handbook/docs/releases)
links the release notes and separately lists apps, beta apps, SDKs, Docker
images, Debian/Ubuntu packages, and the web frontend. It provides no lifecycle
table, support duration, supported-version set, or inheritance rule.

### 4. Distribution channels do not supply Jitsi lifecycle dates

The official [Docker repository](https://github.com/jitsi/docker-jitsi-meet)
defines these image names:

- “All our images are published on the GitHub Container Registry (GHCR).”
- `` `stable` | Points to the latest stable release ``
- `` `stable-NNNN-X` | A stable release ``
- `` `unstable` | Points to the latest unstable release ``
- `` `unstable-YYYY-MM-DD` | Daily unstable release ``

Thus `stable` is a moving pointer, versioned `stable-*` tags identify build
artifacts, and daily `unstable-*` tags identify the unstable channel. Neither
a Docker/GHCR publication timestamp nor repointing `stable` says when a Jitsi
version loses support. Similar, the official [downloads page](https://download.jitsi.org/downloads/)
separates a “Stable build line” from a “Nightly build line” and recommends
stable builds “for more consistent behavior”; that recommendation is neither a
support entitlement nor a support duration.

Release intervals are observations, not rules. They cannot establish EOL merely
because releases are frequent, because `stable` moves, because a newer version
exists, or because an older image or package remains downloadable.

### 5. Hosted offerings are distinct from open-source versions

The [meet.jit.si terms](https://jitsi.org/meet-jit-si-terms-of-service/) say,
“The Service is provided as-is and without support, and 8x8 makes no
commitment or guarantee.” They also allow 8x8 to “at any time, with or without
notice” suspend, terminate, limit, change, modify, downgrade, or update the
service. Those are hosted-service terms, not a lifecycle for self-hosted
releases.

The [JaaS onboarding documentation](https://developer.8x8.com/jaas/docs/jaas-onboarding)
says, “JaaS enables you to develop and integrate Jitsi Meetings functionality
into your web applications” and identifies 8x8.vc as “a special deployment of
Jitsi infrastructure with support for JaaS.” The [JaaS FAQ](https://developer.8x8.com/jaas/docs/faq)
calls JaaS “a fully managed hosted enterprise-ready version of Jitsi” and
states, “8x8 provides commercial Support and SLA for JaaS customers.” It also
states, “8x8 offers no commercial support, SLA or professional services for
Self-hosted Jitsi deployments.”

The JaaS documents provide no supported open-source-version mapping, dated
EOL/EOSsec, fixed support duration, or support-inheritance rule. JaaS service
support and meet.jit.si service terms therefore cannot be assigned to
self-hosted Jitsi web, app, or SDK versions.

## Other sources checked

- Jitsi's [security policy](https://raw.githubusercontent.com/jitsi/jitsi-meet/master/SECURITY.md):
  “We take security very seriously and develop all Jitsi projects to be secure
  and safe.” Its disclosure process names no supported-version set or
  security-support duration.
- The [JaaS FAQ](https://developer.8x8.com/jaas/docs/faq) also says, “8x8 does
  not provide any SLA/support/consultancy for a self hosted Jitsi environment.”
  This is a support boundary, not an EOL statement.
- The stable Debian repository metadata, including its `Date` field, was
  checked as a separate Ubuntu/Debian distribution channel. It states package
  repository freshness, not per-version support termination.

## Why no terminal lifecycle date can be published

The official material establishes release dates and separate channels, but no
source states or authoritatively defines a terminal lifecycle for an open-source
web/server, mobile-app, or mobile-SDK release. No exact vendor date exists to
store, and no explicit vendor duration, release trigger, or named inheritance
rule exists from which a defensible derived date can be calculated under
AGENTS.md. Release cadence, Docker tag behavior, repository freshness, the
existence of newer versions, and Node LTS references are therefore not Jitsi
lifecycle dates.

## Reconsideration criteria

Reconsider only when Jitsi or 8x8 publishes an authoritative, scope-specific
lifecycle source that provides either:

1. a dated EOL or end-of-security-support milestone for a named open-source
   release; or
2. an explicit support duration, release-triggered rule, or named
   support-inheritance rule with an exact base that can be retained verbatim
   with provenance.

The source must identify whether it governs the web/server bundle, mobile apps,
mobile SDKs, Docker/GHCR artifacts, Debian/Ubuntu packages, meet.jit.si, or
JaaS. Until such a statement exists, Jitsi Meet remains absent from lifecycle
coverage and issue #38 should close as **NO-GO**.
