"""Run with python -m engine {import-data,import-hardware,import-opengear,validate,contribute,build}."""
import argparse

from .importer import import_data
from .validation import validate_data, validate_hardware


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import-data", "import-hardware", "import-opengear",
                                            "validate", "contribute", "build"])
    args, rest = parser.parse_known_args()
    # Only `contribute` takes further arguments; every other command stays strict.
    if rest and args.command != "contribute":
        parser.error("unrecognized arguments: " + " ".join(rest))
    if args.command == "import-data":
        import_data()
    elif args.command == "import-hardware":
        from .hardware import import_hardware
        import_hardware()
    elif args.command == "import-opengear":
        from .opengear import import_opengear
        import_opengear()
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
