"""Check generated file bytes against a conservative Pages publication budget."""

import argparse
from pathlib import Path

LIMIT_BYTES = 900_000_000


def check(directory, limit=LIMIT_BYTES):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"Missing site directory: {directory}")
    size = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
    print(f"Published site: {size:,} bytes / {limit:,} byte budget")
    if size > limit:
        raise ValueError(f"Site exceeds publication budget by {size - limit:,} bytes")
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="_site")
    args = parser.parse_args()
    try:
        check(args.directory)
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
