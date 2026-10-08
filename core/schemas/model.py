"""The schema a domain layer hands to core. Core never names a tender field itself."""

from pydantic import BaseModel, Field, model_validator


class RoutingHints(BaseModel):
    """How the extractor picks pages for a group: section kinds and keywords."""

    section_kinds: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class FieldValidation(BaseModel):
    min: float | None = None
    max: float | None = None
    regex: str | None = None


class KeyDef(BaseModel):
    """One typed key of a record field. `keys` makes the key a list of sub-records with
    those keys (one level only)."""

    name: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str = ""
    value_type: str = "text"
    unit: str | None = None
    enum_values: list[str] | None = None
    min: float | None = None
    max: float | None = None
    keys: list["KeyDef"] | None = None


class FieldDef(BaseModel):
    path: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    label: str
    group: str
    value_type: str
    unit: str | None = None
    required: bool = False
    help_text: str = ""
    enum_values: list[str] | None = None
    # For a list type whose items are records: the keys every item may carry.
    item_keys: list[str] | None = None
    # For a record, or a list of records with typed values: its keys, each with a type.
    keys: list[KeyDef] | None = None
    validation: FieldValidation = Field(default_factory=FieldValidation)
    review_order: int = 0

    @property
    def key(self) -> str:
        """The field's name inside its group's model output: the last path segment."""
        return self.path.rsplit(".", 1)[1]


class FieldGroup(BaseModel):
    """Fields extracted together in one call so they share context."""

    name: str = Field(pattern=r"^[a-z0-9_]+$")
    prompt_name: str = "extract"
    # The group's own prompt version, when it is ahead of the version a run asks for.
    prompt_version: str | None = None
    # At most this many pages for the group, when fewer than the general cap: a group
    # whose answer must come from one call sets it to the pages of one call.
    max_pages: int | None = None
    routing: RoutingHints = Field(default_factory=RoutingHints)
    guidance: str = ""
    # A derived group is never sent to the model: its candidates are written by
    # deterministic code from the object's decided fields (run mode "derived").
    derived: bool = False


class ExtractionSchema(BaseModel):
    name: str
    version: str
    groups: list[FieldGroup]
    fields: list[FieldDef]
    cross_field_rules: list[str] = Field(default_factory=list)
    # Rules that see a whole run (its object, its candidates and their evidence).
    run_rules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "ExtractionSchema":
        group_names = [group.name for group in self.groups]
        if len(set(group_names)) != len(group_names):
            raise ValueError("duplicate group name")
        paths = [field.path for field in self.fields]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate field path")
        for field in self.fields:
            if field.group not in group_names:
                raise ValueError(f"{field.path} names unknown group {field.group!r}")
        for group in self.groups:
            keys = [field.key for field in self.fields_in(group.name)]
            if len(set(keys)) != len(keys):
                raise ValueError(f"group {group.name!r} has two fields with the same key")
            if not keys:
                raise ValueError(f"group {group.name!r} has no fields")
        return self

    def fields_in(self, group: str) -> list[FieldDef]:
        return sorted(
            (field for field in self.fields if field.group == group),
            key=lambda field: (field.review_order, field.path),
        )

    def field(self, path: str) -> FieldDef:
        for field in self.fields:
            if field.path == path:
                return field
        raise KeyError(path)
