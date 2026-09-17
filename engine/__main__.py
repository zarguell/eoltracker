"""Run with python -m engine {refresh,import-data,import-hardware,import-opengear,validate,contribute,build}.

The import commands are the registry's source ids, so adding a source adds its
command. ``refresh`` runs every registered source through the per-source
transaction and reports each outcome.
"""
import argparse
import os

from . import sources
from .validation import validate_data, validate_hardware

IMPORT_COMMANDS = tuple(source.id for source in sources.all_sources())
COMMANDS = IMPORT_COMMANDS + ("refresh", "validate", "contribute", "build")


def run_refresh():
    """Refresh every registered source; report each outcome and exit accordingly.

    A source that fails is rolled back to its committed records, the others
    still refresh, and the run fails only when every source failed. The summary
    goes to stdout and, when the workflow supplied one, to the run's step
    summary as well.
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
    return refresh.exit_code(outcomes)


def run_import(source_id):
    """Refresh one registered source into the committed data directory."""
    source = sources.source(source_id)
    detail = source.run()
    print(f"{source_id}: {detail}" if detail else source_id)


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
        from . import changes, feeds, openeox, site
        site.build()
        openeox.build(validate_data())
        manifest = None
        manifest_path = site.ROOT / "data" / "manifest.json"
        if manifest_path.exists():
            import json
            manifest = json.loads(manifest_path.read_text())
        feeds.build(validate_data(), validate_hardware(), manifest=manifest)
        history_path = site.ROOT / "data" / "opengear-changes.json"
        if history_path.exists():
            import json
            changes.build(json.loads(history_path.read_text()), site.ROOT / "_site")
        print("Built website, v1 endpoints and feeds in _site/")


if __name__ == "__main__":
    main()
