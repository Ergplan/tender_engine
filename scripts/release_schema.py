"""Management command: freeze the field definitions of a pack version.

  python -m scripts.release_schema            write released/<version>.yaml for every pack
  python -m scripts.release_schema --check    say which versions are released; change nothing
  python -m scripts.release_schema --from-root <dir>   the same, for pack files kept elsewhere
                                              (used once, to release v1 from the git history)

A released file lists, per tender type, every field with its type, unit, allowed values and
record keys. The pack loader refuses to load a released version whose fields differ from its
file, and checks a version that reads an earlier one field by field against the earlier
file (tender/services/packs.py: verify_versions). Release a version once runs made under
it are to be kept: after that a change to a field needs a new version.
"""

import argparse
import sys
from pathlib import Path

import yaml

from tender.services.packs import (
    PACKS_ROOT,
    Catalog,
    load_catalog,
    released_file,
    type_signature,
)

HEADER = (
    "# Field definitions of pack `{pack}` as released in version {version}: per tender type,\n"
    "# every field with what a stored value depends on (type, unit, allowed values, keys).\n"
    "# Written by `python -m scripts.release_schema`. Never edited by hand: the pack loader\n"
    "# compares schema versions against this file.{note}\n"
)


def released_text(catalog: Catalog, pack: str, version: str, note: str = "") -> str:
    types = {
        name: type_signature(compiled.fields)
        for name, compiled in sorted(catalog.types.items())
        if compiled.pack == pack and compiled.schema.version == version
    }
    body = yaml.safe_dump(
        {"pack": pack, "version": version, "types": types},
        sort_keys=True,
        allow_unicode=True,
        width=1000,
    )
    return HEADER.format(pack=pack, version=version, note=note) + body


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--from-root", type=Path, default=PACKS_ROOT)
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv[1:])
    catalog = load_catalog(args.from_root)
    versions = sorted({(c.pack, c.schema.version) for c in catalog.types.values()})
    for pack, version in versions:
        target = released_file(PACKS_ROOT / pack, version)
        note = f"\n# {args.note}" if args.note else ""
        text = released_text(catalog, pack, version, note)
        if target.is_file():
            # The loader has already verified that the compiled fields equal this file.
            print(f"{pack} {version}: released ({target.relative_to(PACKS_ROOT)})")
        elif args.check:
            print(f"{pack} {version}: not released")
        else:
            target.parent.mkdir(exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"{pack} {version}: wrote {target.relative_to(PACKS_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
