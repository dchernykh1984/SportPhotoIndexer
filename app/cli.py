"""Command line: ``python -m app.cli index|check FOLDER``."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from app import indexer
from app.index_format import INDEX_FILE, problems


def _index(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    index, report = indexer.scan(folder, indexer.load(folder), previews=args.previews)
    print(
        f"{len(index['photos'])} photos: {report.added} new, {report.changed} changed,"
        f" {report.removed} gone, {report.previews} previews"
    )
    for message in report.messages:
        print(message)
    if args.csv:
        applied, unknown = indexer.import_csv(index, Path(args.csv))
        print(f"bibs set on {applied} photos from {args.csv}")
        if unknown:
            print(f"not in the folder: {', '.join(unknown[:10])}")
    print(f"{INDEX_FILE} {'written' if indexer.save(folder, index) else 'unchanged'}")
    return 0


def _check(args: argparse.Namespace) -> int:
    index = indexer.load(Path(args.folder), validate=False)
    if index is None:
        print(f"no {INDEX_FILE} in {args.folder}")
        return 1
    found = problems(index)
    for problem in found:
        print(problem)
    print("the site would accept it" if not found else f"{len(found)} problem(s)")
    return 1 if found else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sport-photo-indexer")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="scan a folder and write its index")
    index.add_argument("folder")
    index.add_argument("--csv", help="bibs from a 'file;bibs' table")
    index.add_argument("--previews", action="store_true", help="a preview per photo")
    index.set_defaults(run=_index)
    check = commands.add_parser("check", help="check an index as the site would")
    check.add_argument("folder")
    check.set_defaults(run=_check)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (indexer.IndexError_, OSError, csv.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
