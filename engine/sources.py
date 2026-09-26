"""The source registry: one descriptor per deterministic source of the catalog.

Every published record carries ``provenance.verifier`` naming the pipeline that
parsed it, and every pipeline owns exactly one slice of the catalog: the
endoflife.date software importer, the eosl.date hardware collector, the
Opengear lifecycle/configurator collector. Those facts used to be restated
wherever they were needed — a URL-to-label table in the site, an ``if verifier
== "deterministic-opengear"`` branch in validation, a list of vendor steps in
the publish workflow — which meant a new source had to be remembered in four
places. Here they are declared once, as data:

* ``id`` — the CLI command that refreshes this source (``import-opengear``).
* ``module``/``entry`` — the callable that does the refresh, imported lazily so
  enumerating sources never imports a network module.
* ``verifier``/``category`` — the provenance this source owns and the catalog
  it writes into. Validation requires a committed record's verifier to name a
  registered source *and* that source's category to match the record, so a
  hardware record can never claim the software importer and vice versa.
* ``name``/``url``/``urls``/``attribution`` — the presentation facts: what the
  source is called, where it lives, every page a refresh reads, and the
  sentence the site credits it with. The site never restates these.

Adding a vendor source is therefore additive: register a descriptor (and, if
the source re-derives its records offline, a ``validator`` path) and the CLI,
the refresh transaction and site attribution all pick it up without a list to
edit. The module imports nothing from the rest of ``engine``.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from urllib.parse import urlparse

# Upstream pages. Defined once here; the collectors import them rather than
# restating a URL that the registry and the site also publish.
ENDOFLIFE_DATE_API = "https://endoflife.date/api/v1/products/"
ENDOFLIFE_DATE_SITE = "https://endoflife.date/"
EOSL_DATE = "https://eosl.date/"
EOSL_DATE_SITEMAP = "https://eosl.date/sitemap-coreapp-product-families.xml"
OPENGEAR_LIFECYCLE = "https://opengear.com/end-life-products"
OPENGEAR_CONFIGURE = "https://opengear.com/configure/"
NVIDIA_VGPU_DOCS = "https://docs.nvidia.com/vgpu/index.html"
GITHUB_GHES_RELEASES = "https://docs.github.com/en/enterprise-server@latest/admin/all-releases"
CEPH_RELEASES = "https://docs.ceph.com/en/latest/releases/"
CEPH_RELEASES_DATA = "https://raw.githubusercontent.com/ceph/ceph/main/doc/releases/releases.yml"
NETSCALER_SOURCE = "https://www.citrix.com/support/product-lifecycle/product-matrix.html"
NETSCALER_LEGACY = "https://www.citrix.com/support/product-lifecycle/legacy-product-matrix.html"
XENSERVER_SUPPORT = "https://www.xenserver.com/support"
XENSERVER_STATEMENT = ("https://support.citrix.com/external/article?articleUrl=CTX692513-"
                       "prepare-for-citrix-hypervisor-82-cumulative-update-1-end-of-life")
FLATCAR_RELEASES = "https://www.flatcar.org/releases-json/releases.json"
FLATCAR_CHANNELS = ("https://www.flatcar.org/docs/latest/updates-releases/releases/"
                    "switching-channels")
OPENEULER_DOWNLOAD = "https://www.openeuler.org/en/download/"
OPENEULER_API = "https://www.openeuler.org/api/mirrors/"
OPENEULER_LIFECYCLE = "https://www.openeuler.org/en/other/lifecycle/"
OPENEULER_WHITEPAPER = ("https://www.openeuler.org/whitepaper/en/openEuler%2024.03%20LTS%20SP4%20"
                        "Technical%20White%20Paper.pdf")
OPENEULER_ANNOUNCEMENT_2403 = ("https://www.openeuler.org/en/news/20240612-openEuler%2024.03%20"
                               "LTS-The%20First%20AI-Native%20Open%20Source%20Operating%20System/")
OPENEULER_ANNOUNCEMENT_SP4 = ("https://www.openeuler.org/en/news/20260701-openEuler%2024.03%20"
                              "LTS%20SP4/20260701-openEuler%2024.03%20LTS%20SP4.html")
CHECKPOINT_LIFECYCLE = "https://www.checkpoint.com/support-services/support-life-cycle-policy/"
ODOO_SUPPORT = "https://www.odoo.com/documentation/master/administration/standard_extended_support.html"
SAMBA_RELEASE_PLANNING = "https://wiki.samba.org/index.php/Samba_Release_Planning"
CISCO_EOL_INDEX = "https://www.cisco.com/c/en/us/support/eol/index.html"
CISCO_IOS_RELEASES = "https://www.cisco.com/c/en/us/products/ios-nx-os-software/ios-software-releases-listing.html"
CISCO_NXOS_LIFECYCLE = "https://www.cisco.com/c/en/us/products/collateral/ios-nx-os-software/nx-os-software/guide_c07-658595.html"
CISCO_ATTRIBUTION = ("Cisco IOS and NX-OS release-train lifecycle published directly by Cisco's "
                     "end-of-sale/end-of-life listings and lifecycle support statements; dates carry "
                     "the day precision Cisco states, and the terminal Last Date of Support is the "
                     "stored end of life.")
PROGRESS_OPENEDGE_LIFECYCLE = "https://docs.progress.com/bundle/openedge-life-cycle/page/OpenEdge-Life-Cycle.html"
PROGRESS_CORTICON_LIFECYCLE = "https://docs.progress.com/bundle/corticon-life-cycle/page/Corticon-Life-Cycle.html"
PROGRESS_CORTICON_JS_LIFECYCLE = ("https://docs.progress.com/bundle/corticon-js-life-cycle/page/"
                                  "Corticon.js-Life-Cycle.html")
PROGRESS_WHATSUP_LIFECYCLE = "https://docs.progress.com/bundle/whatsup-gold-life-cycle/page/Life-Cycle.html"
PROGRESS_WHATSUP_EOS_POLICY = "https://docs.progress.com/bundle/product-eos-policy/page/Policy.html"
PROGRESS_SITEFINITY_POLICY = "https://www.progress.com/support/sitefinity-lifecycle-policy"
SOLARWINDS_SITEMAP = "https://documentation.solarwinds.com/sitemap.xml"
SOLARWINDS_DOCS = "https://documentation.solarwinds.com/en/success_center/"
SOLARWINDS_ATTRIBUTION = ("SolarWinds product lifecycle published directly by SolarWinds' own "
                          "release-history and retired-product tables; the EoL effective date is "
                          "the terminal support end, and the EoL announcement and EoE effective "
                          "date stay the vendor's own cells because SolarWinds never states them "
                          "as a support end.")
PROGRESS_ATTRIBUTION = ("Progress Software product lifecycle published directly by Progress's own "
                        "product life cycle guides; the Active and Retired columns become general "
                        "availability and end of life at the precision the vendor's own cell "
                        "states, and Sunset, Deprecated and the offering columns stay the vendor's "
                        "own cells because Progress never states them as a support end.")

# Attribution is published text (the site and the API docs print it verbatim):
# eosl.date states no license for the data it republishes, so it is cited;
# Opengear's own pages are credited as the vendor's.
EOSL_ATTRIBUTION = ("Hardware lifecycle data comes from eosl.date by Subash Geetha Krishnan, "
                    "aggregated from public vendor announcements.")
OPENGEAR_ATTRIBUTION = ("Lifecycle dates published directly by Opengear; grouped parts and contract "
                        "exceptions are retained below.")
ENDOFLIFE_DATE_ATTRIBUTION = ("Software lifecycle data comes from endoflife.date, a community catalog of "
                              "public vendor lifecycle statements, used under its MIT license.")
CEPH_ATTRIBUTION = ("Ceph community release branch lifecycle published directly by the Ceph project's release "
                    "documentation. A current branch carries only an estimated end of life, which is retained as "
                    "the vendor's own cell and never normalized into a firm date.")
NVIDIA_ATTRIBUTION = ("NVIDIA vGPU software branch lifecycle published directly by NVIDIA; "
                      "dates carry the month precision the vendor's table states.")
NETSCALER_ATTRIBUTION = ("NetScaler ADC firmware lifecycle published directly by Citrix's product "
                         "matrices; EOM never fills a normalized milestone because the vendor states support "
                         "continues after it.")
XENSERVER_ATTRIBUTION = ("XenServer hypervisor lifecycle published directly by Citrix's and XenServer's own "
                         "product matrices and the public CTX692513 support article; only each table's own EOL "
                         "and EOS columns become milestones, and NSC, EOM and EOES stay the vendor's own cells.")
FLATCAR_ATTRIBUTION = ("Flatcar Container Linux Stable stream lifecycle published directly by the Flatcar "
                       "project's release feed and channel documentation; each stream's end of life is derived "
                       "from the documented next-major-Stable-release trigger and labelled as such.")
OPENEULER_ATTRIBUTION = ("openEuler community release lifecycle published directly by the openEuler "
                         "community's release catalog, download page, lifecycle policy and release "
                         "documents; release cards state an end of life at the month precision the "
                         "community gives, and the innovation support window derived from the published "
                         "policy is labelled as derived.")
# A researched record's verifier names a contributor, not a pipeline: the
# registry leaves those to engine.contribute, which admits them against their
# own stored citation.
RESEARCHED_PREFIX = "researched-"


class RegistryError(ValueError):
    """A registry lookup or contract violation."""


class UnknownVerifier(RegistryError):
    """A committed record names a deterministic verifier no source registered."""


class UnknownSource(RegistryError):
    """No source is registered under that CLI command id."""


class CategoryMismatch(RegistryError):
    """A record claims a registered source that owns a different catalog."""


@dataclass(frozen=True)
class Page:
    """One page a source's refresh reads, and the label the site credits it with."""

    url: str
    label: str


@dataclass(frozen=True)
class Source:
    """One deterministic source of the catalog."""

    id: str
    module: str
    entry: str
    verifier: str
    category: str
    name: str
    url: str
    pages: tuple[Page, ...]
    attribution: str
    # Optional per-source paths, filled in only where the source has them:
    # `validator` is the dotted callable re-deriving one of its records offline,
    # `report` the sidecar file (relative to the data directory) its refresh
    # publishes to account for every source row it saw.
    validator: str = ""
    report: str = ""

    @property
    def urls(self):
        """Every page URL this source's refresh reads."""
        return tuple(page.url for page in self.pages)

    def run(self, directory=None):
        """Refresh this source into ``directory`` (the data directory).

        The implementation module is imported here, not at registration, so a
        process that only needs the registry (validation, a site build, the CLI
        help) never imports an HTTP client. Returns the source's own one-line
        summary of what it did.
        """
        module = importlib.import_module(self.module)
        return getattr(module, self.entry)(directory)


SOURCES = (
    Source(
        id="import-data",
        module="engine.importer",
        entry="import_data",
        verifier="deterministic-endoflife-date-v1",
        category="software",
        name="endoflife.date",
        url=ENDOFLIFE_DATE_SITE,
        pages=(Page(ENDOFLIFE_DATE_SITE, "endoflife.date"),
               Page(ENDOFLIFE_DATE_API, "endoflife.date API")),
        attribution=ENDOFLIFE_DATE_ATTRIBUTION,
    ),
    Source(
        id="import-hardware",
        module="engine.hardware",
        entry="import_hardware",
        verifier="deterministic-eosl-date",
        category="hardware",
        name="eosl.date",
        url=EOSL_DATE,
        pages=(Page(EOSL_DATE, "eosl.date"),
               Page(EOSL_DATE_SITEMAP, "eosl.date product family sitemap")),
        attribution=EOSL_ATTRIBUTION,
    ),
    Source(
        id="import-opengear",
        module="engine.opengear",
        entry="import_opengear",
        verifier="deterministic-opengear",
        category="hardware",
        name="Opengear",
        url=OPENGEAR_LIFECYCLE,
        # The configurator leads: a catalog record is read from the listing that
        # carries its SKU, and a lifecycle row from the retirement table.
        pages=(Page(OPENGEAR_CONFIGURE, "Opengear product configurator"),
               Page(OPENGEAR_LIFECYCLE, "Opengear end-of-life product list")),
        attribution=OPENGEAR_ATTRIBUTION,
        # Opengear records re-derive themselves from their own stored cells, so
        # the registry is where validation finds that per-source check; its
        # refresh also publishes the per-row accounting sidecar below.
        validator="engine.opengear.validate_record",
        report="opengear-import.json",
    ),
    Source(
        id="import-vgpu",
        module="engine.vgpu",
        entry="import_vgpu",
        verifier="deterministic-nvidia-vgpu",
        category="software",
        name="NVIDIA vGPU docs",
        url=NVIDIA_VGPU_DOCS,
        pages=(Page(NVIDIA_VGPU_DOCS, "NVIDIA vGPU software lifecycle"),),
        attribution=NVIDIA_ATTRIBUTION,
        # Every stored milestone re-derives from the record's own stored cells,
        # and the refresh accounts for every branch row it saw.
        validator="engine.vgpu.validate_record",
        report="vgpu-import.json",
    ),
    Source(
        id="import-ghes",
        module="engine.ghes",
        entry="import_ghes",
        verifier="deterministic-github-ghes",
        category="software",
        name="GitHub Enterprise Server",
        url=GITHUB_GHES_RELEASES,
        pages=(Page(GITHUB_GHES_RELEASES, "GitHub Enterprise Server releases"),
               Page(GITHUB_GHES_RELEASES + ".md", "GitHub Enterprise Server release table")),
        attribution="GitHub Enterprise Server release and support-end dates published directly by GitHub.",
        validator="engine.ghes.validate_record",
        report="ghes-import.json",
    ),
    Source(
        id="import-netscaler",
        module="engine.netscaler",
        entry="import_netscaler",
        verifier="deterministic-netscaler",
        category="software",
        name="Citrix product lifecycle matrix",
        url=NETSCALER_SOURCE,
        pages=(Page(NETSCALER_SOURCE, "Citrix product matrix (NetScaler ADC)"),
               Page(NETSCALER_LEGACY, "Citrix legacy product matrix")),
        attribution=NETSCALER_ATTRIBUTION,
        validator="engine.netscaler.validate_record",
        report="netscaler-import.json",
    ),
    Source(
        id="import-xenserver",
        module="engine.xenserver",
        entry="import_xenserver",
        verifier="deterministic-xenserver",
        category="software",
        name="XenServer lifecycle",
        url=XENSERVER_SUPPORT,
        # The current vendor table leads: a reader checking a published line
        # opens the page Citrix's own matrix names as XenServer's lifecycle
        # source. The legacy matrix supplies the historical lines and the
        # support article states the 8.2 line's terminal date, which the
        # refresh cross-checks against the legacy row.
        pages=(Page(XENSERVER_SUPPORT, "XenServer product matrix"),
               Page(NETSCALER_LEGACY, "Citrix legacy product matrix"),
               Page(XENSERVER_STATEMENT, "Citrix support article CTX692513")),
        attribution=XENSERVER_ATTRIBUTION,
        validator="engine.xenserver.validate_record",
        report="xenserver-import.json",
    ),
    Source(
        id="import-ceph",
        module="engine.ceph",
        entry="import_ceph",
        verifier="deterministic-ceph",
        category="software",
        name="Ceph releases",
        url=CEPH_RELEASES,
        pages=(Page(CEPH_RELEASES, "Ceph release lifecycle"),
               Page(CEPH_RELEASES_DATA, "Ceph release metadata (releases.yml)")),
        attribution=CEPH_ATTRIBUTION,
        validator="engine.ceph.validate_record",
        report="ceph-import.json",
    ),
    Source(
        id="import-powerdns-authoritative",
        module="engine.powerdns",
        entry="import_authoritative",
        verifier="deterministic-powerdns-authoritative",
        category="software",
        name="PowerDNS Authoritative Server",
        url="https://doc.powerdns.com/authoritative/appendices/EOL.html",
        pages=(Page("https://doc.powerdns.com/authoritative/appendices/EOL.html",
                    "PowerDNS Authoritative release lifecycle"),),
        attribution="PowerDNS Authoritative community lifecycle; approximate dates are not deadlines. Commercial support agreements may differ.",
        validator="engine.powerdns.validate_record",
        report="powerdns-authoritative-import.json",
    ),
    Source(
        id="import-checkpoint",
        module="engine.checkpoint",
        entry="import_checkpoint",
        verifier="deterministic-checkpoint",
        category="software",
        name="Check Point Support Life Cycle Policy",
        url=CHECKPOINT_LIFECYCLE,
        pages=(Page(CHECKPOINT_LIFECYCLE, "Check Point support life cycle policy"),),
        attribution="Check Point Security Gateway & Management lifecycle; dates retain the month precision stated by the vendor.",
        validator="engine.checkpoint.validate_record",
        report="checkpoint-import.json",
    ),
    Source(
        id="import-odoo",
        module="engine.odoo",
        entry="import_odoo",
        verifier="deterministic-odoo",
        category="software",
        name="Odoo",
        url=ODOO_SUPPORT,
        pages=(Page(ODOO_SUPPORT, "Odoo standard and extended support"),),
        attribution="Odoo release and standard-support calendar; standard support ending is not terminal or security support ending. Planned dates remain vendor text.",
        validator="engine.odoo.validate_record",
        report="odoo-import.json",
    ),
    Source(
        id="import-samba",
        module="engine.samba",
        entry="import_samba",
        verifier="deterministic-samba",
        category="software",
        name="Samba Release Planning",
        url=SAMBA_RELEASE_PLANNING,
        pages=(Page(SAMBA_RELEASE_PLANNING, "Samba release planning and supported release lifetime"),),
        attribution="Samba release-series lifecycle published directly by the Samba project; "
                    "~-marked future dates are the vendor's own forecasts and never deadlines.",
        validator="engine.samba.validate_record",
        report="samba-import.json",
    ),
    Source(
        id="import-cisco-ios",
        module="engine.cisco_software",
        entry="import_ios",
        verifier="deterministic-cisco-ios",
        category="software",
        name="Cisco IOS",
        url=CISCO_EOL_INDEX,
        pages=(Page(CISCO_EOL_INDEX, "Cisco end-of-sale and end-of-life product listing"),
               Page(CISCO_IOS_RELEASES, "Cisco IOS software releases"),
               Page("https://www.cisco.com/c/en/us/support/ios-nx-os-software/", "Cisco IOS 15 software trains")),
        attribution=CISCO_ATTRIBUTION,
        validator="engine.cisco_software.validate_ios_record",
        report="cisco-ios-import.json",
    ),
    Source(
        id="import-cisco-nx-os",
        module="engine.cisco_software",
        entry="import_nx_os",
        verifier="deterministic-cisco-nx-os",
        category="software",
        name="Cisco NX-OS",
        url=CISCO_NXOS_LIFECYCLE,
        pages=(Page(CISCO_NXOS_LIFECYCLE, "Cisco NX-OS software lifecycle support statement"),),
        attribution=CISCO_ATTRIBUTION,
        validator="engine.cisco_software.validate_nx_os_record",
        report="cisco-nx-os-import.json",
    ),
    Source(
        id="import-visio",
        module="engine.visio",
        entry="import_visio",
        verifier="deterministic-microsoft-visio",
        category="software",
        name="Microsoft Lifecycle (Visio)",
        url="https://learn.microsoft.com/en-us/lifecycle/products/visio-2024",
        pages=tuple(
            Page(f"https://learn.microsoft.com/en-us/lifecycle/products/{slug}",
                 f"Microsoft Lifecycle: {label}")
            for slug, label in (
                ("visio-2024", "Visio 2024"),
                ("visio-ltsc-2024", "Visio LTSC 2024"),
                ("visio-2021", "Visio 2021"),
                ("visio-ltsc-2021", "Visio LTSC 2021"),
                ("visio-plan-2", "Visio Plan 2"),
                ("visio-2019", "Visio 2019"),
                ("visio-2016", "Visio 2016"),
                ("visio-2013", "Visio 2013"),
                ("visio-2010", "Visio 2010"),
                ("visio-2007", "Visio 2007"),
                ("visio-2003", "Visio 2003"),
            )
        ),
        attribution="Microsoft Visio lifecycle dates published directly by Microsoft's Lifecycle product pages.",
        validator="engine.visio.validate_record",
        report="visio-import.json",
    ),
    Source(
        id="import-entra-connect",
        module="engine.entra_connect",
        entry="import_entra_connect",
        verifier="deterministic-entra-connect",
        category="software",
        name="Microsoft Entra Connect",
        url="https://learn.microsoft.com/en-us/lifecycle/products/azure-active-directory-ad-connect",
        pages=(
            Page("https://learn.microsoft.com/en-us/lifecycle/products/azure-active-directory-ad-connect",
                 "Microsoft Lifecycle: Entra Connect"),
            Page("https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/reference-connect-version-history",
                 "Microsoft Entra Connect version history"),
            Page("https://learn.microsoft.com/en-us/entra/identity/hybrid/connect/reference-connect-version-history-archive",
                 "Microsoft Entra Connect version history archive"),
        ),
        attribution="Microsoft Entra Connect lifecycle and release history published directly by Microsoft.",
        validator="engine.entra_connect.validate_record",
        report="entra-connect-import.json",
    ),
    Source(
        id="import-teamcity",
        module="engine.teamcity",
        entry="import_teamcity",
        verifier="deterministic-teamcity",
        category="software",
        name="JetBrains TeamCity release cycle",
        url="https://www.jetbrains.com/help/teamcity/teamcity-release-cycle.html",
        pages=(
            Page("https://www.jetbrains.com/help/teamcity/teamcity-release-cycle.html",
                 "TeamCity On-Premises release cycle"),
            Page("https://www.jetbrains.com/help/teamcity/previous-releases-downloads.html",
                 "TeamCity On-Premises releases"),
        ),
        attribution="TeamCity On-Premises lifecycle from JetBrains' release-cycle policy and release catalog; EOS/EOS dates derived from the dated triggering releases are labeled as such.",
        validator="engine.teamcity.validate_record",
        report="teamcity-import.json",
    ),
    Source(
        id="import-flatcar",
        module="engine.flatcar",
        entry="import_flatcar",
        verifier="deterministic-flatcar",
        category="software",
        name="Flatcar Container Linux releases",
        url=FLATCAR_RELEASES,
        # The feed leads: it is the record's own source, and a reader checking a
        # published stream opens the row it was read from. The channel
        # documentation is registered beside it because it states the rule every
        # derived end of life rests on.
        pages=(Page(FLATCAR_RELEASES, "Flatcar Container Linux release feed"),
               Page(FLATCAR_CHANNELS, "Flatcar Container Linux channel documentation")),
        attribution=FLATCAR_ATTRIBUTION,
        validator="engine.flatcar.validate_record",
        report="flatcar-import.json",
    ),
    Source(
        id="import-iis",
        module="engine.iis",
        entry="import_iis",
        verifier="deterministic-microsoft-iis",
        category="software",
        name="Microsoft IIS lifecycle",
        url="https://learn.microsoft.com/en-us/lifecycle/products/internet-information-services-iis",
        pages=(
            Page("https://learn.microsoft.com/en-us/lifecycle/products/internet-information-services-iis",
                 "Microsoft Lifecycle: IIS"),
            Page("https://learn.microsoft.com/en-us/lifecycle/faq/fixed-policy",
                 "Microsoft Fixed Lifecycle Policy: component support"),
            Page("https://learn.microsoft.com/en-us/windows-server/administration/performance-tuning/role/web-server/tuning-iis-10",
                 "IIS 10.0 on Windows Server 2022"),
            Page("https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2022",
                 "Microsoft Lifecycle: Windows Server 2022"),
            Page("https://learn.microsoft.com/en-us/powershell/module/servermanager/install-windowsfeature?view=windowsserver2025-ps",
                 "Web Server (IIS) role on Windows Server 2025"),
            Page("https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2025",
                 "Microsoft Lifecycle: Windows Server 2025"),
            Page("https://learn.microsoft.com/en-us/lifecycle/products/windows-10-home-and-pro",
                 "Microsoft Lifecycle: Windows 10 Home and Pro"),
            Page("https://learn.microsoft.com/en-us/lifecycle/products/windows-10-enterprise-and-education",
                 "Microsoft Lifecycle: Windows 10 Enterprise and Education"),
        ),
        attribution="Microsoft IIS lifecycle dates published directly by Microsoft; omitted platform scopes inherit only the explicitly named parent platform's terminal support date, with the rule and parent retained as provenance.",
        validator="engine.iis.validate_record",
        report="iis-import.json",
    ),
    Source(
        id="import-openui5",
        module="engine.openui5",
        entry="import_openui5",
        verifier="deterministic-openui5",
        category="software",
        name="OpenUI5 release and maintenance data",
        url="https://openui5.org/releases.html",
        pages=(
            Page("https://openui5.org/releases.html", "OpenUI5 releases"),
            Page("https://openui5versiontracker.cfapps.eu10.hana.ondemand.com/OpenUI5ReleasesInfo",
                 "OpenUI5 release feed"),
            Page("https://sdk.openui5.org/versionoverview.json", "OpenUI5 version overview"),
            Page("https://sdk.openui5.org/version.json", "OpenUI5 current version"),
            Page("https://ui5.github.io/docs/02_Read-Me-First/versioning-and-maintenance-of-openui5-91f0214.md",
                 "OpenUI5 versioning and maintenance policy"),
        ),
        attribution="OpenUI5 release and branch maintenance data published directly by the OpenUI5 project; EOM/EOMM/EOCP remain raw lifecycle fields until their precision and semantics are normalized.",
        validator="engine.openui5.validate_record",
        report="openui5-import.json",
    ),
    Source(
        id="import-openeuler",
        module="engine.openeuler",
        entry="import_openeuler",
        verifier="deterministic-openeuler",
        category="software",
        name="openEuler community releases",
        url=OPENEULER_DOWNLOAD,
        # The download page leads: it is the release history a reader checking a
        # published row opens, and it states the one milestone this record
        # publishes directly. The catalog supplies the identities, the lifecycle
        # page the rule one date derives from, and the white paper and
        # announcements the release dates the page does not state.
        pages=(Page(OPENEULER_DOWNLOAD, "openEuler community release downloads"),
               Page(OPENEULER_API, "openEuler release catalog API"),
               Page(OPENEULER_LIFECYCLE, "openEuler community version lifecycle"),
               Page(OPENEULER_WHITEPAPER, "openEuler 24.03 LTS SP4 technical white paper"),
               Page(OPENEULER_ANNOUNCEMENT_2403, "openEuler 24.03 LTS release announcement"),
               Page(OPENEULER_ANNOUNCEMENT_SP4, "openEuler 24.03 LTS SP4 release announcement")),
        attribution=OPENEULER_ATTRIBUTION,
        validator="engine.openeuler.validate_record",
        report="openeuler-import.json",
    ),
    Source(
        id="import-progress-openedge",
        module="engine.progress",
        entry="import_openedge",
        verifier="deterministic-progress-openedge",
        category="software",
        name="Progress OpenEdge",
        url=PROGRESS_OPENEDGE_LIFECYCLE,
        # One page carries all four tables: the two product lines' current
        # schedules and their two retired histories.
        pages=(Page(PROGRESS_OPENEDGE_LIFECYCLE, "OpenEdge product life cycle"),),
        attribution=PROGRESS_ATTRIBUTION,
        validator="engine.progress.validate_openedge",
        report="progress-openedge-import.json",
    ),
    Source(
        id="import-progress-corticon",
        module="engine.progress",
        entry="import_corticon",
        verifier="deterministic-progress-corticon",
        category="software",
        name="Progress Corticon",
        url=PROGRESS_CORTICON_LIFECYCLE,
        # Two products, two pages: Corticon and Corticon.js publish the same
        # table shape under their own bundles.
        pages=(Page(PROGRESS_CORTICON_LIFECYCLE, "Corticon product life cycle"),
               Page(PROGRESS_CORTICON_JS_LIFECYCLE, "Corticon.js product life cycle")),
        attribution=PROGRESS_ATTRIBUTION,
        validator="engine.progress.validate_corticon",
        report="progress-corticon-import.json",
    ),
    Source(
        id="import-progress-whatsup-gold",
        module="engine.progress",
        entry="import_whatsup",
        verifier="deterministic-progress-whatsup-gold",
        category="software",
        name="Progress WhatsUp Gold",
        url=PROGRESS_WHATSUP_LIFECYCLE,
        # The life cycle page carries the release schedules; the End-of-Sale
        # policy states what an offering's EoS date means, which the collector
        # requires verbatim to exclude the offering rows on that basis.
        pages=(Page(PROGRESS_WHATSUP_LIFECYCLE, "WhatsUp Gold product life cycle"),
               Page(PROGRESS_WHATSUP_EOS_POLICY, "WhatsUp Gold End-of-Sale policy")),
        attribution=PROGRESS_ATTRIBUTION,
        validator="engine.progress.validate_whatsup",
        report="progress-whatsup-gold-import.json",
    ),
    Source(
        id="import-progress-sitefinity",
        module="engine.progress",
        entry="import_sitefinity",
        verifier="deterministic-progress-sitefinity",
        category="software",
        name="Progress Sitefinity",
        url=PROGRESS_SITEFINITY_POLICY,
        pages=(Page(PROGRESS_SITEFINITY_POLICY, "Sitefinity lifecycle policy"),),
        attribution=PROGRESS_ATTRIBUTION,
        validator="engine.progress.validate_sitefinity",
        report="progress-sitefinity-import.json",
    ),
    Source(
        id="import-solarwinds",
        module="engine.solarwinds",
        entry="import_solarwinds",
        verifier="deterministic-solarwinds",
        category="software",
        name="SolarWinds release histories",
        url=SOLARWINDS_SITEMAP,
        # The sitemap is the discovery surface: it states one release-history
        # page per product family, which is what makes the family set complete
        # without a hand-kept list. A family's own page is where its dates live.
        pages=(Page(SOLARWINDS_SITEMAP, "SolarWinds documentation sitemap"),
               Page(SOLARWINDS_DOCS + "ncm/content/release_notes/release_history.htm",
                    "SolarWinds release histories")),
        attribution=SOLARWINDS_ATTRIBUTION,
        validator="engine.solarwinds.validate_history",
        report="solarwinds-import.json",
    ),
)

# Registry id -> source, and verifier -> source: one source per verifier, which
# is what makes a refresh's ownership slice well defined.
BY_ID = {source.id: source for source in SOURCES}
BY_VERIFIER = {source.verifier: source for source in SOURCES}
if len(BY_ID) != len(SOURCES) or len(BY_VERIFIER) != len(SOURCES):
    raise RegistryError("Duplicate source id or verifier")
# Page URL -> label, exact match first, then the site root it belongs to. Two
# sources may read the same page (Citrix's legacy product matrix carries both
# the NetScaler ADC tab and the XenServer tabs), and a page has one published
# name: both sources must register the same label, so neither can silently
# relabel a page another source already publishes.
PAGES = {}
for source in SOURCES:
    for page in source.pages:
        existing = PAGES.setdefault(page.url, page.label)
        if existing != page.label:
            raise RegistryError(f"Page {page.url} is registered as both {existing!r} and "
                                f"{page.label!r}; a shared page carries one label")


def all_sources():
    """Every registered source, in refresh order."""
    return SOURCES


def source(source_id):
    """The source registered under a CLI command id."""
    try:
        return BY_ID[source_id]
    except KeyError:
        raise UnknownSource(f"No source registered as {source_id!r}") from None


def source_for(verifier):
    """The source owning ``verifier``; raises for an unregistered one.

    This is the enforcement path: a deterministic verifier that no source
    registered means a record claims a pipeline that is not installed, so the
    catalog would not be reproducible from this checkout.
    """
    try:
        return BY_VERIFIER[verifier]
    except KeyError:
        raise UnknownVerifier(
            f"Unknown deterministic verifier {verifier!r}; register the source in engine/sources.py "
            f"or mark the record as researched") from None


def sources_for(verifier):
    """Every source owning ``verifier``; empty for researched or unknown ones.

    The presentation path: a researched record's verifier names a contributor,
    not a pipeline, and its citation is its own — so the callers that render or
    attribute a record ask here and fall back, while validation asks
    :func:`source_for` and refuses.
    """
    found = BY_VERIFIER.get(verifier)
    return (found,) if found else ()


def verify_category(verifier, category):
    """The source owning ``verifier``, once its catalog matches ``category``."""
    found = source_for(verifier)
    if found.category != category:
        raise CategoryMismatch(
            f"Verifier {verifier!r} owns the {found.category} catalog, not {category}")
    return found


def source_urls(verifier):
    """Every page URL the source owning ``verifier`` reads."""
    return tuple(page.url for source in sources_for(verifier) for page in source.pages)


def source_label(url):
    """The label for a published source URL, or its hostname when unrecognised.

    Records carry per-page source URLs (a record's own page, the notice that
    named it, a vendor PDF), so labels cannot be enumerated per record; the
    registry labels the pages it knows and the fallback names the host honestly.
    """
    if url in PAGES:
        return PAGES[url]
    for page, label in PAGES.items():
        if url.startswith(page):
            return label
    if "//" in url:
        host = urlparse(url).hostname or url
        return host[4:] if host.startswith("www.") else host
    return url


def attribution(verifier):
    """The attribution sentence for a verifier's source, else an empty string."""
    found = BY_VERIFIER.get(verifier)
    return found.attribution if found else ""


def record_validator(found):
    """The per-record validator of a source that re-derives its own records.

    Imported lazily so validation pulls in a collector only for records that
    collector owns.
    """
    if not found.validator:
        return None
    module, _, name = found.validator.rpartition(".")
    return getattr(importlib.import_module(module), name)


def validate_verifier(verifier, category):
    """Check a committed record's verifier against the registry.

    Returns the owning source, or None when the verifier is not the registry's
    business: a ``researched-<contributor>`` verifier names a contribution, not
    a pipeline, and ``engine.contribute`` admits those against their own stored
    citation. Anything else must be a registered source owning ``category``,
    which is what stops a record claiming a pipeline this checkout does not
    install — or a pipeline that owns a different catalog.
    """
    if not isinstance(verifier, str) or not verifier:
        raise UnknownVerifier("Record without a verifier")
    if verifier.startswith(RESEARCHED_PREFIX):
        return None
    return verify_category(verifier, category)
