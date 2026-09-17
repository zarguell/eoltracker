"""Run with python -m engine {import-data,validate,build}."""
import argparse

from .importer import import_data
from .validation import validate_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import-data", "validate", "build"])
    args = parser.parse_args()
    if args.command == "import-data":
        import_data()
    elif args.command == "validate":
        records = validate_data()
        print(f"Validated {len(records)} products and {sum(len(p['releases']) for p in records)} releases")
    else:
        from . import site, openeox
        site.build()
        openeox.build(validate_data())
        print("Built website and v1 endpoints in _site/")


if __name__ == "__main__":
    main()
