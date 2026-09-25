"""Run with python -m engine {refresh,import-data,import-hardware,import-opengear,validate,contribute,build}.

The import commands are the registry's source ids, so adding a source adds its
command. ``refresh`` runs every registered source through the per-source
transaction and reports each outcome.
"""
import argparse
import os
import sys

from . import sources
from .validation import validate_data, validate_hardware

IMPORT_COMMANDS = tuple(source.id for source in sources.all_sources())
COMMANDS = IMPORT_COMMANDS + ("refresh", "validate", "contribute", "build")


def run_refresh():
    """Refresh every registered source; report each outcome and exit accordingly.

    A source that fails is rolled back to its committed records, the others
    still refresh, and the run fails when *any* source failed (#87): a partial
    refresh is a partially stale catalog, and internal consistency validation
    cannot tell. The summary goes to stdout and, when the workflow supplied one,
    to the run's step summary as well.
    """
    from . import refresh

    outcomes = refresh.refresh_all(sources.all_sources())
    for line in refresh.report(outcomes):
        print(line)
    summary = refresh.summary_markdown(outcomes)
    path = os.environ.get(refresh.STEP_SUMMARY)
    if summary is not None and path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(summary)
    verdict = refresh.freshness(outcomes)
    if verdict["blocking"]:
        print(f"::error::Catalog refresh incomplete: {verdict['refreshed']}/{verdict['sources']} sources "
              f"refreshed; failed: {', '.join(verdict['failed']) or 'none'}.")
    return refresh.exit_code(outcomes)


def run_import(source_id):
    """Refresh one registered source into the committed data directory (#94).

    The documented single-source commands write several files — records, the
    manifest, and the source's own sidecar or ledger — so a failure partway
    through must not leave a mixed catalog. They run through the same
    `refresh.refresh_source` transaction the aggregate refresh uses, which
    snapshots the data directory first and restores it byte-for-byte on any
    failure, instead of the previous sequential writes with no rollback.
    """
    from . import refresh

    source = sources.source(source_id)
    outcome = refresh.refresh_source(source)
    if not outcome.ok:
        print(outcome.line(), file=sys.stderr)
        raise SystemExit(1)
    print(outcome.line())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    args, rest = parser.parse_known_args(argv)
    # Only `contribute` takes further arguments; every other command stays strict.
    if rest and args.command != "contribute":
        parser.error("unrecognized arguments: " + " ".join(rest))
    if args.command == "refresh":
        raise SystemExit(run_refresh())
    if args.command in IMPORT_COMMANDS:
        run_import(args.command)
    elif args.command == "validate":
        records = validate_data()
        message = f"Validated {len(records)} products and {sum(len(p['releases']) for p in records)} releases"
        hardware = validate_hardware()
        if hardware:
            message += f", {len(hardware)} hardware models"
        print(message)
    elif args.command == "contribute":
        from . import contribute
        raise SystemExit(contribute.main(rest))
    else:
        from . import site
        # `site.build` owns every publication stage — pages, v1 endpoints,
        # OpenEoX, feeds and the change ledger — and publishes them together
        # through its staging tree, so the CLI does not append stages to an
        # already-visible `_site/` (#114).
        result = site.build()
        print(f"Built website, v1 endpoints, OpenEoX, feeds and changes in {result['out']}/ "
              f"({result['records']} products, {result['hardware_records']} hardware records, "
              f"{result['staging']['files']} files)")


if __name__ == "__main__":
    main()
