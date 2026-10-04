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
    roles: list[str]
    section_kinds: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class RawField(_Strict):
    section: str
    label: str
    type: str
    unit: str | None = None
    required: bool = False
    help: str = ""
    enum: list[str] | None = None
    item_keys: list[str] | None = None
    min: float | None = None
    max: float | None = None
    regex: str | None = None


class RawFile(_Strict):
    pack: str
    version: str | None = None
    sector: str | None = None
    subdomains: list[str] = Field(default_factory=list)
    type: str | None = None
    includes: list[str] = Field(default_factory=list)
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
    review_order: int


class CompiledSection(BaseModel):
    name: str
    label: str
    prompt: str
    roles: list[str]
    order: int


@dataclass(frozen=True)
class CompiledType:
    tender_type: str
    pack: str
    schema: ExtractionSchema
    sections: list[CompiledSection]
    fields: list[TenderField]

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
    rules: list[str] = []
    for parent_name in raw.inherits:
        parent = _type_file(pack_dir, parent_name, (*seen, tender_type))
        _merge(sections, parent.sections, "section", path)
        _merge(fields, parent.fields, "field", path)
        includes += [name for name in parent.includes if name not in includes]
        required += [name for name in parent.required if name not in required]
        rules += [name for name in parent.cross_field_rules if name not in rules]
    _merge(sections, raw.sections, "section", path)
    _merge(fields, raw.fields, "field", path)
    includes += [name for name in raw.includes if name not in includes]
    required += [name for name in raw.required if name not in required]
    rules += [name for name in raw.cross_field_rules if name not in rules]
    return raw.model_copy(
        update={
            "sections": sections,
            "fields": fields,
            "includes": includes,
            "required": required,
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
    sources = ((core, core_path), (pack, pack_dir / "pack.yaml"), (own, pack_dir))
    for section_name in included:
        for raw, where in sources:
            for path, field in raw.fields.items():
                if field.section != section_name:
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
                        validation=FieldValidation(min=field.min, max=field.max, regex=field.regex),
                        review_order=order,
                    )
                )
    for raw, where in sources:
        stray = sorted({f.section for f in raw.fields.values()} - set(sections))
        if stray:
            raise PackError(f"{where}: field(s) name unknown section(s) {stray}")
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
    return CompiledType(
        tender_type=tender_type,
        pack=pack.pack,
        schema=schema,
        sections=[
            CompiledSection(
                name=name,
                label=sections[name].label,
                prompt=sections[name].prompt,
                roles=sections[name].roles,
                order=order,
            )
            for order, name in enumerate(included, start=1)
        ],
        fields=fields,
    )


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
