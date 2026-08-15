#!/usr/bin/env python3
"""Strip outputs and normalize kernel metadata across the course notebooks.

Usage:
  python scripts/strip_outputs.py NOTEBOOK [NOTEBOOK ...]
  python scripts/strip_outputs.py --all

Clears every code cell's outputs and execution_count, and pins the notebook
metadata the course standardizes on (kernelspec "Python 3 (ipykernel)" /
python3, language_info python 3.12). Files are rewritten only when something
actually changed, so a clean tree stays byte-identical. Run before committing;
scripts/validate_notebooks.py fails notebooks with unstripped outputs.
"""

import argparse
import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parent.parent

KERNELSPEC = {"display_name": "Python 3 (ipykernel)",
              "language": "python",
              "name": "python3"}
LANGUAGE_INFO = {"name": "python", "version": "3.12"}


def discover_all() -> list[Path]:
    chapters = sorted(ROOT.glob("[0-9][0-9]-*.ipynb"))
    appendices = sorted((ROOT / "appendices").glob("A-*.ipynb"))
    return chapters + appendices


def strip_one(path: Path) -> bool:
    """Strip a notebook in place; return True when the file was rewritten."""
    nb = nbformat.read(path, as_version=4)
    before = nbformat.writes(nb)
    for cell in nb.cells:
        if cell.cell_type == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        cell.get("metadata", {}).pop("execution", None)   # nbclient timestamps re-dirty diffs
    nb.metadata["kernelspec"] = dict(KERNELSPEC)
    nb.metadata["language_info"] = dict(LANGUAGE_INFO)
    after = nbformat.writes(nb)
    if after == before:
        return False
    nbformat.write(nb, path)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip outputs/execution counts and normalize kernel "
                    "metadata; rewrites only files that changed.")
    parser.add_argument("notebooks", nargs="*", metavar="NOTEBOOK",
                        help="notebook paths to strip")
    parser.add_argument("--all", action="store_true",
                        help="strip all numbered chapters and appendices")
    args = parser.parse_args()

    if args.all and args.notebooks:
        parser.error("pass either --all or explicit notebook paths, not both")
    if not args.all and not args.notebooks:
        parser.print_usage(sys.stderr)
        print("error: nothing to strip -- pass notebook paths or --all",
              file=sys.stderr)
        sys.exit(2)

    paths = discover_all() if args.all else [Path(p) for p in args.notebooks]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"error: notebook not found: {p}", file=sys.stderr)
        sys.exit(2)

    stripped = 0
    for path in paths:
        if strip_one(path):
            stripped += 1
    print(f"strip_outputs: {stripped} rewritten, {len(paths) - stripped} "
          f"already clean, {len(paths)} total")


if __name__ == "__main__":
    main()
