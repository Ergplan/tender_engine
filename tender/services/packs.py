"""Domain packs: YAML schemas compiled into core extraction schemas, one per tender type.

A pack is data plus prompts plus validators under tender/domain_packs/<pack>/. The core
pack holds the fields every tender has (common.yaml); a sector pack holds pack.yaml (its
own common fields) and one YAML per tender type. A type resolves to exactly one pack and
compiles to the schema `tender.<type>` in the pack's version. Compilation is done once,
at start-up; a conflict between inherited types is an error, never silently resolved.
"""

import importlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from core.llm.registry import CORE_PROMPT_ROOT
from core.schemas import (
    ExtractionSchema,
    FieldDef,
    FieldGroup,
    FieldValidation,
    KeyDef,
    RoutingHints,
    SchemaRegistry,
)
from tender.domain_packs.core.value_types import VALUE_TYPES
from tender.models import DOCUMENT_ROLES

PACKS_ROOT = Path(__file__).resolve().parents[1] / "domain_packs"
CORE_PACK = "core"
_CORE_PATH = re.compile(r"^core\.[a-z0-9_]+\.[a-z0-9_]+$")
_SECTOR_PATH = re.compile(r"^sector\.([a-z0-9_]+)\.([a-z0-9_]+)\.[a-z0-9_]+$")


class PackError(ValueError):
    """A pack file is malformed, or two definitions conflict."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectionDef(_Strict):
    """A review section and extraction group: its prompt, the document roles it is read
    from, and the routing hints the extractor uses to pick pages."""

    label: str
    prompt: str
    # The section's prompt version when it is ahead of the run's (see FieldGroup).
    prompt_version: str | None = None
    max_pages: int | None = None
    roles: list[str]
    section_kinds: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class RawKey(_Strict):
    """One typed key of a record field; `keys` makes it a list of sub-records."""

    label: str = ""
    type: str = "text"
    unit: str | None = None
    enum: list[str] | None = None
    min: float | None = None
    max: float | None = None
    keys: dict[str, "RawKey"] | None = None

    def compiled(self, name: str) -> KeyDef:
        return KeyDef(
            name=name,
            label=self.label or name.replace("_", " ").capitalize(),
            value_type="list" if self.keys else self.type,
            unit=self.unit,
            enum_values=self.enum,
            min=self.min,
            max=self.max,
            keys=[key.compiled(sub) for sub, key in self.keys.items()] if self.keys else None,
        )


class RawField(_Strict):
    section: str
    label: str
    type: str
    unit: str | None = None
    required: bool = False
    help: str = ""
    enum: list[str] | None = None
    item_keys: list[str] | None = None
    keys: dict[str, RawKey] | None = None
    min: float | None = None
    max: float | None = None
    regex: str | None = None

    def key_defs(self) -> list[KeyDef] | None:
        return [key.compiled(name) for name, key in self.keys.items()] if self.keys else None


class RawFile(_Strict):
    pack: str
    version: str | None = None
    # Earlier versions whose runs are read under this one. Checked field by field against
    # released/<version>.yaml when the pack is loaded (see verify_reads).
    reads_versions: list[str] = Field(default_factory=list)
    # Per earlier version: fields this version changes, whose sections are read again.
    # Their candidates from runs of the earlier version are not read.
    read_again: dict[str, list[str]] = Field(default_factory=dict)
    sector: str | None = None
    subdomains: list[str] = Field(default_factory=list)
    type: str | None = None
    includes: list[str] = Field(default_factory=list)
    # Common fields this type leaves out because they do not apply to it.
    excludes: list[str] = Field(default_factory=list)
    inherits: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    sections: dict[str, SectionDef] = Field(default_factory=dict)
    fields: dict[str, RawField] = Field(default_factory=dict)
    cross_field_rules: list[str] = Field(default_factory=list)
    run_rules: list[str] = Field(default_factory=list)


class TenderField(BaseModel):
    """One compiled field of a tender type, with where it comes from."""

    path: str
    namespace: str
    domain: str | None
    subdomain: str | None
    section: str
    label: str
    value_type: str
    unit: str | None
    required: bool
    help_text: str
    enum_values: list[str] | None
    item_keys: list[str] | None
    keys: list[KeyDef] | None = None
    review_order: int


class CompiledSection(BaseModel):
    name: str
    label: str
    prompt: str
    prompt_version: str | None = None
    roles: list[str]
    order: int


@dataclass(frozen=True)
class CompiledType:
    tender_type: str
    pack: str
    schema: ExtractionSchema
    sections: list[CompiledSection]
    fields: list[TenderField]
    # Earlier schema versions whose runs are read under this schema.
    reads_versions: tuple[str, ...] = ()
    # Per earlier version, the fields of this type that it does not hand on: this version
    # changed them, so their candidates from runs of the earlier version are not read.
    not_read_from: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def section(self, name: str) -> CompiledSection:
        return next(section for section in self.sections if section.name == name)


@dataclass(frozen=True)
class Catalog:
    """Every compiled tender type, with the rules, value types and prompt roots they need."""

    types: dict[str, CompiledType]
    cross_field_rules: dict[str, Any]
    run_rules: dict[str, Any]
    prompt_roots: tuple[Path, ...]

    def get(self, tender_type: str) -> CompiledType:
        try:
            return self.types[tender_type]
        except KeyError:
            raise LookupError(f"no schema for tender type {tender_type!r}") from None

    def register(self, registry: SchemaRegistry) -> None:
        """Register value types, rules and schemas with core. Safe to call twice."""
        registered = set(registry.names())
        if any((c.schema.name, c.schema.version) in registered for c in self.types.values()):
            return
        for value_type in VALUE_TYPES:
            registry.value_types.register(value_type)
        for name, rule in self.cross_field_rules.items():
            registry.register_rule(name, rule)
        for name, run_rule in self.run_rules.items():
            registry.register_run_rule(name, run_rule)
        for compiled in self.types.values():
            registry.register(compiled.schema)
            for earlier in compiled.reads_versions:
                registry.register(compiled.schema.model_copy(update={"version": earlier}))
            for earlier, paths in compiled.not_read_from:
                registry.exclude_fields(compiled.schema.name, earlier, paths)


def schema_name(tender_type: str) -> str:
    return f"tender.{tender_type}"


def _read(path: Path) -> RawFile:
    try:
        return RawFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise PackError(f"{path}: {exc}") from exc


def _namespace(path: str, where: Path) -> tuple[str, str | None, str | None]:
    if _CORE_PATH.match(path):
        return "core", None, None
    match = _SECTOR_PATH.match(path)
    if match:
        return "sector", match.group(1), match.group(2)
    raise PackError(
        f"{where}: {path!r} is neither core.<section>.<field> nor "
        "sector.<domain>.<subdomain>.<field>"
    )


def _merge[T](into: dict[str, T], new: dict[str, T], what: str, where: Path) -> None:
    for name, value in new.items():
        if name in into and into[name] != value:
            raise PackError(f"{where}: conflicting definitions of {what} {name!r}")
        into.setdefault(name, value)


def _type_file(pack_dir: Path, tender_type: str, seen: tuple[str, ...] = ()) -> RawFile:
    """A type file with the types it inherits folded in. Conflicts are errors."""
    if tender_type in seen:
        raise PackError(f"{pack_dir}: type {tender_type!r} inherits itself")
    path = pack_dir / f"{tender_type}.yaml"
    if not path.is_file():
        raise PackError(f"{pack_dir}: no type file for {tender_type!r}")
    raw = _read(path)
    if raw.type != tender_type:
        raise PackError(f"{path}: `type` must be {tender_type!r}")
    sections: dict[str, SectionDef] = {}
    fields: dict[str, RawField] = {}
    includes: list[str] = []
    required: list[str] = []
    excludes: list[str] = []
    rules: list[str] = []
    for parent_name in raw.inherits:
        parent = _type_file(pack_dir, parent_name, (*seen, tender_type))
        _merge(sections, parent.sections, "section", path)
        _merge(fields, parent.fields, "field", path)
        includes += [name for name in parent.includes if name not in includes]
        required += [name for name in parent.required if name not in required]
        excludes += [name for name in parent.excludes if name not in excludes]
        rules += [name for name in parent.cross_field_rules if name not in rules]
    _merge(sections, raw.sections, "section", path)
    _merge(fields, raw.fields, "field", path)
    includes += [name for name in raw.includes if name not in includes]
    required += [name for name in raw.required if name not in required]
    excludes += [name for name in raw.excludes if name not in excludes]
    rules += [name for name in raw.cross_field_rules if name not in rules]
    return raw.model_copy(
        update={
            "sections": sections,
            "fields": fields,
            "includes": includes,
            "required": required,
            "excludes": excludes,
            "cross_field_rules": rules,
            "inherits": [],
        }
    )


def compile_type(pack_dir: Path, tender_type: str, core_dir: Path | None = None) -> CompiledType:
    """Resolve one tender type against the core pack and its own pack, and freeze it."""
    core_path = (core_dir or PACKS_ROOT / CORE_PACK) / "common.yaml"
    core, pack = _read(core_path), _read(pack_dir / "pack.yaml")
    own = _type_file(pack_dir, tender_type)
    if own.pack != pack.pack:
        raise PackError(f"{pack_dir}: type {tender_type!r} names pack {own.pack!r}")
    if tender_type not in pack.subdomains:
        raise PackError(f"{pack_dir}: {tender_type!r} is not a subdomain of pack {pack.pack!r}")

    sections: dict[str, SectionDef] = {}
    for raw, where in ((core, core_path), (pack, pack_dir / "pack.yaml"), (own, pack_dir)):
        for name, section in raw.sections.items():
            if name in sections:
                raise PackError(f"{where}: section {name!r} is defined twice")
            unknown = sorted(set(section.roles) - set(DOCUMENT_ROLES))
            if unknown or not section.roles:
                raise PackError(f"{where}: section {name!r} has unknown role(s) {unknown}")
            sections[name] = section
    missing = [name for name in own.includes if name not in sections]
    if missing:
        raise PackError(f"{pack_dir}: {tender_type!r} includes unknown section(s) {missing}")
    included = [*own.includes, *(name for name in own.sections if name not in own.includes)]

    fields: list[TenderField] = []
    defs: list[FieldDef] = []
    seen: set[str] = set()
    excluded: set[str] = set()
    sources = ((core, core_path), (pack, pack_dir / "pack.yaml"), (own, pack_dir))
    for section_name in included:
        for raw, where in sources:
            for path, field in raw.fields.items():
                if field.section != section_name:
                    continue
                if path in own.excludes and raw is not own:
                    excluded.add(path)
                    continue
                if path in seen:
                    raise PackError(f"{where}: field {path!r} is defined twice")
                seen.add(path)
                namespace, domain, subdomain = _namespace(path, where)
                if raw is core and namespace != "core":
                    raise PackError(f"{where}: the core pack may only define core.* fields")
                if raw is not core and (
                    namespace != "sector"
                    or domain != pack.sector
                    or subdomain not in pack.subdomains
                ):
                    raise PackError(
                        f"{where}: {path!r} must be sector.{pack.sector}.<subdomain>.<field>"
                    )
                order = len(fields) + 1
                required = field.required or path in own.required
                fields.append(
                    TenderField(
                        path=path,
                        namespace=namespace,
                        domain=domain,
                        subdomain=subdomain,
                        section=section_name,
                        label=field.label,
                        value_type=field.type,
                        unit=field.unit,
                        required=required,
                        help_text=field.help,
                        enum_values=field.enum,
                        item_keys=field.item_keys,
                        keys=field.key_defs(),
                        review_order=order,
                    )
                )
                defs.append(
                    FieldDef(
                        path=path,
                        label=field.label,
                        group=section_name,
                        value_type=field.type,
                        unit=field.unit,
                        required=required,
                        help_text=field.help,
                        enum_values=field.enum,
                        item_keys=field.item_keys,
                        keys=field.key_defs(),
                        validation=FieldValidation(min=field.min, max=field.max, regex=field.regex),
                        review_order=order,
                    )
                )
    for raw, where in sources:
        stray = sorted({f.section for f in raw.fields.values()} - set(sections))
        if stray:
            raise PackError(f"{where}: field(s) name unknown section(s) {stray}")
    unknown_excluded = sorted(set(own.excludes) - excluded)
    if unknown_excluded:
        raise PackError(
            f"{pack_dir}: {tender_type!r} excludes field(s) it would not have: {unknown_excluded}"
        )
    unknown_required = sorted(set(own.required) - seen)
    if unknown_required:
        raise PackError(f"{pack_dir}: {tender_type!r} requires unknown field(s) {unknown_required}")

    rules = list(
        dict.fromkeys([*core.cross_field_rules, *pack.cross_field_rules, *own.cross_field_rules])
    )
    run_rules = list(dict.fromkeys([*core.run_rules, *pack.run_rules]))
    try:
        schema = ExtractionSchema(
            name=schema_name(tender_type),
            version=pack.version or "v1",
            groups=[
                FieldGroup(
                    name=name,
                    prompt_name=sections[name].prompt,
                    prompt_version=sections[name].prompt_version,
                    max_pages=sections[name].max_pages,
                    routing=RoutingHints(
                        section_kinds=sections[name].section_kinds,
                        keywords=sections[name].keywords,
                    ),
                )
                for name in included
            ],
            fields=defs,
            cross_field_rules=rules,
            run_rules=run_rules,
        )
    except ValueError as exc:
        raise PackError(f"{pack_dir}: type {tender_type!r}: {exc}") from exc
    reads_versions = tuple(v for v in pack.reads_versions if v != (pack.version or "v1"))
    not_read_from = verify_versions(
        pack_dir, tender_type, pack.version or "v1", reads_versions, pack.read_again, fields
    )
    return CompiledType(
        tender_type=tender_type,
        pack=pack.pack,
        schema=schema,
        sections=[
            CompiledSection(
                name=name,
                label=sections[name].label,
                prompt=sections[name].prompt,
                prompt_version=sections[name].prompt_version,
                roles=sections[name].roles,
                order=order,
            )
            for order, name in enumerate(included, start=1)
        ],
        fields=fields,
        reads_versions=reads_versions,
        not_read_from=not_read_from,
    )


RELEASED = "released"
Signature = dict[str, Any]


def _key_signature(key: KeyDef) -> Signature:
    signature: Signature = {"type": key.value_type}
    if key.unit:
        signature["unit"] = key.unit
    if key.enum_values:
        signature["enum"] = list(key.enum_values)
    if key.keys:
        signature["keys"] = {sub.name: _key_signature(sub) for sub in key.keys}
    return signature


def field_signature(field: TenderField) -> Signature:
    """What a stored value of the field depends on: its type, unit, allowed values and the
    keys of a record. Labels, help text, bounds, the section and whether it is required
    may change without making a stored candidate mean something else."""
    signature: Signature = {"type": field.value_type}
    if field.unit:
        signature["unit"] = field.unit
    if field.enum_values:
        signature["enum"] = list(field.enum_values)
    if field.item_keys:
        signature["item_keys"] = list(field.item_keys)
    if field.keys:
        signature["keys"] = {key.name: _key_signature(key) for key in field.keys}
    return signature


def type_signature(fields: list[TenderField]) -> dict[str, Signature]:
    return {field.path: field_signature(field) for field in sorted(fields, key=lambda f: f.path)}


def released_file(pack_dir: Path, version: str) -> Path:
    return pack_dir / RELEASED / f"{version}.yaml"


def read_released(pack_dir: Path, version: str) -> dict[str, dict[str, Signature]] | None:
    """The field definitions of a released version, per tender type, or None if the pack
    has no such file."""
    path = released_file(pack_dir, version)
    if not path.is_file():
        return None
    return _parse_released(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=32)
def _parse_released(path: Path, modified: int) -> dict[str, dict[str, Signature]]:
    """Parsed once per file and change: the files are large, and every tender type of a
    pack is checked against the same two of them when the packs are loaded."""
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=loader) or {}  # noqa: S506
    types = data.get("types")
    if not isinstance(types, dict):
        raise PackError(f"{path}: expected a mapping `types`")
    return types


def verify_versions(
    pack_dir: Path,
    tender_type: str,
    version: str,
    reads_versions: tuple[str, ...],
    read_again: dict[str, list[str]],
    fields: list[TenderField],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Check this type against the released versions of its pack. Raises PackError, naming
    every field at fault, when:

    - the version is released (released/<version>.yaml exists) and a field of it has been
      added, removed or changed since: a released version is frozen, make a new one;
    - the version says it reads an earlier one but that one has no released file;
    - a field of the earlier version is missing here: its candidates would be orphaned;
    - a field of the earlier version is defined differently here and the pack does not
      list it under `read_again` for that version.

    Returns, per earlier version, the changed fields listed under `read_again`: their
    sections are read again, and their candidates from earlier runs are not read."""
    current = type_signature(fields)
    where = f"{pack_dir}: type {tender_type!r}"
    frozen = (read_released(pack_dir, version) or {}).get(tender_type)
    if frozen is not None and frozen != current:
        differing = sorted(
            path for path in set(frozen) | set(current) if frozen.get(path) != current.get(path)
        )
        raise PackError(
            f"{where}: version {version} is released and frozen, but these fields differ from "
            f"{released_file(pack_dir, version).name}: {differing}. Make a new version."
        )
    unknown = sorted(set(read_again) - set(reads_versions))
    if unknown:
        raise PackError(f"{where}: read_again names version(s) {unknown} that are not read")
    not_read: list[tuple[str, tuple[str, ...]]] = []
    for earlier in reads_versions:
        released = read_released(pack_dir, earlier)
        if released is None:
            raise PackError(
                f"{where}: version {version} reads {earlier}, but "
                f"{RELEASED}/{earlier}.yaml does not exist; without it the two cannot be compared"
            )
        before = released.get(tender_type, {})
        declared = set(read_again.get(earlier, []))
        orphaned = sorted(path for path in before if path not in current)
        changed = sorted(
            path for path in before if path in current and before[path] != current[path]
        )
        undeclared = [path for path in changed if path not in declared]
        stale = sorted(path for path in declared if path in before and path not in changed)
        problems = []
        if orphaned:
            problems.append(f"removed, so their {earlier} candidates would be orphaned: {orphaned}")
        if undeclared:
            problems.append(
                f"defined differently than in {earlier} and not listed under read_again: "
                f"{undeclared}"
            )
        if stale:
            problems.append(f"listed under read_again but unchanged since {earlier}: {stale}")
        if problems:
            raise PackError(
                f"{where}: version {version} cannot read {earlier}. Fields " + "; ".join(problems)
            )
        if changed:
            not_read.append((earlier, tuple(changed)))
    return tuple(not_read)


def load_catalog(packs_root: Path = PACKS_ROOT) -> Catalog:
    """Compile every type of every sector pack under the root."""
    types: dict[str, CompiledType] = {}
    cross_field_rules: dict[str, Any] = {}
    run_rules: dict[str, Any] = {}
    prompt_roots = [CORE_PROMPT_ROOT]
    pack_dirs = sorted(path.parent for path in packs_root.glob("*/pack.yaml"))
    for pack_dir in (packs_root / CORE_PACK, *pack_dirs):
        if (pack_dir / "prompts").is_dir():
            prompt_roots.append(pack_dir / "prompts")
        module = importlib.import_module(f"tender.domain_packs.{pack_dir.name}.validation")
        for name, rule in module.CROSS_FIELD_RULES.items():
            if name in cross_field_rules:
                raise PackError(f"{pack_dir}: rule {name!r} is defined by two packs")
            cross_field_rules[name] = rule
        for name, rule in module.RUN_RULES.items():
            if name in run_rules:
                raise PackError(f"{pack_dir}: run rule {name!r} is defined by two packs")
            run_rules[name] = rule
    for pack_dir in pack_dirs:
        for tender_type in _read(pack_dir / "pack.yaml").subdomains:
            if not (pack_dir / f"{tender_type}.yaml").is_file():
                continue  # a subdomain without its own type, such as `common`
            if tender_type in types:
                raise PackError(f"{pack_dir}: type {tender_type!r} belongs to two packs")
            types[tender_type] = compile_type(pack_dir, tender_type, packs_root / CORE_PACK)
    return Catalog(
        types=types,
        cross_field_rules=cross_field_rules,
        run_rules=run_rules,
        prompt_roots=tuple(prompt_roots),
    )


def build_registry() -> tuple[SchemaRegistry, Catalog]:
    """The schema registry the API and the worker start with: every tender type registered."""
    registry, catalog = SchemaRegistry(), load_catalog()
    catalog.register(registry)
    return registry, catalog
