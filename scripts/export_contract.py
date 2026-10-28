"""Management command: the contract any caller codes against (Stage 7, Block 6 a and d).

  python -m scripts.export_contract --write   regenerate docs/contracts/*
  python -m scripts.export_contract --check   exit 1 if a file is out of date, or if the
                                              snapshot schema is no longer an additive
                                              change of the committed contract v1

Three files under docs/contracts/:

- snapshot.v1.schema.json: the JSON Schema of `GET /tenders/{id}/fields` (the snapshot),
  contract v1, additive only: a property, once published, keeps its name and type and
  never becomes required; new properties may be added. `--check` holds the live model to
  the committed file (`additive_change`), and `tests/scripts/test_export_contract.py`
  does the same.
- openapi.v1.json: OpenAPI 3.1 of the REST v1 for callers (submit, status, fields,
  changes, ask, review link, webhooks; the published view and compare), built without a
  database. ChatGPT Actions and the OpenAI Responses API read it as it is.
- functions.v1.json: the same operations as function definitions (name, description,
  JSON-Schema parameters), the shape `tools=[{"type": "function", ...}]` takes, for a
  caller that wants to hand the API to a model directly.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from api.middleware import errors
from api.v1.tenders import ask, contract, published
from tender.services.snapshot import TenderSnapshot

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs" / "contracts"
SNAPSHOT = CONTRACTS / "snapshot.v1.schema.json"
OPENAPI = CONTRACTS / "openapi.v1.json"
FUNCTIONS = CONTRACTS / "functions.v1.json"
ROUTERS = (contract.router, ask.router, published.router)
TITLE = "Tender Intelligence Engine, REST v1 for callers"


def snapshot_schema() -> dict[str, Any]:
    schema = TenderSnapshot.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Tender snapshot, contract v1"
    return schema


def openapi_document() -> dict[str, Any]:
    app = FastAPI(title=TITLE, version="1.0.0")
    errors.install(app)
    for router in ROUTERS:
        app.include_router(router, prefix="/api/v1")
    document: dict[str, Any] = app.openapi()
    document["servers"] = [{"url": "https://34.131.65.108", "description": "the VM"}]
    document["components"].setdefault("securitySchemes", {})["ApiKey"] = {
        "type": "http",
        "scheme": "bearer",
        "description": "An API key (`tie_live_…`) in the Authorization header, with the "
        "X-Public-Request: 1 header; scopes read, model, write, review:mint.",
    }
    document["security"] = [{"ApiKey": []}]
    return document


def function_definitions(document: dict[str, Any]) -> list[dict[str, Any]]:
    """One function per operation: the path and query parameters and the JSON or form body
    as one flat parameters object, the way a model is given a tool."""
    functions = []
    for path, methods in sorted(document["paths"].items()):
        for method, operation in methods.items():
            name = _function_name(operation.get("operationId") or f"{method}_{path}")
            properties: dict[str, Any] = {}
            required: list[str] = []
            for parameter in operation.get("parameters", []):
                if parameter.get("in") == "header":
                    continue  # identity headers are the caller's transport, not an argument
                properties[parameter["name"]] = {
                    **parameter.get("schema", {}),
                    "description": parameter.get("description", f"{parameter['in']} parameter"),
                }
                if parameter.get("required"):
                    required.append(parameter["name"])
            body = operation.get("requestBody", {}).get("content", {})
            for media, spec in body.items():
                schema = _resolved(document, spec.get("schema", {}))
                for prop, definition in schema.get("properties", {}).items():
                    if _is_binary(definition):
                        definition = {
                            "type": "string",
                            "description": "the file, base64; or send source_url instead",
                        }
                    properties[prop] = definition
                required.extend(schema.get("required", []))
                properties["_content_type"] = {"type": "string", "const": media}
            functions.append(
                {
                    "type": "function",
                    "name": name,
                    "description": (operation.get("description") or operation.get("summary") or "")
                    .strip()
                    .replace("\n", " "),
                    "x-method": method.upper(),
                    "x-path": path,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": sorted(set(required)),
                        "additionalProperties": False,
                    },
                }
            )
    return functions


def _is_binary(definition: dict[str, Any]) -> bool:
    """An upload: FastAPI writes it as `format: binary` (3.0) or `contentMediaType` (3.1),
    plain or as a member of `anyOf` when the file is optional."""
    members = [definition, *definition.get("anyOf", [])]
    return any(m.get("format") == "binary" or "contentMediaType" in m for m in members)


def _function_name(operation_id: str) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", operation_id.lower()).strip("_")
    return re.sub(r"_api_v1.*$", "", name) or name


def _resolved(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        resolved: dict[str, Any] = document["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        return resolved
    return schema


def additive_change(committed: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """What the current snapshot schema took away from the committed one: a property
    gone or retyped, a property newly required, in any definition. Empty when the change
    is additive."""
    problems: list[str] = []
    committed_defs = {"": committed, **committed.get("$defs", {})}
    current_defs = {"": current, **current.get("$defs", {})}
    for name, old in committed_defs.items():
        new = current_defs.get(name)
        where = name or "snapshot"
        if new is None:
            problems.append(f"{where}: definition removed")
            continue
        for prop, old_type in old.get("properties", {}).items():
            new_type = new.get("properties", {}).get(prop)
            if new_type is None:
                problems.append(f"{where}.{prop}: removed")
            elif _type_of(new_type) != _type_of(old_type):
                problems.append(
                    f"{where}.{prop}: type {_type_of(old_type)} became {_type_of(new_type)}"
                )
        newly_required = set(new.get("required", [])) - set(old.get("required", []))
        for prop in sorted(newly_required):
            if prop in old.get("properties", {}):
                problems.append(f"{where}.{prop}: became required")
    return problems


def _type_of(definition: dict[str, Any]) -> str:
    if "type" in definition:
        return str(definition["type"])
    if "$ref" in definition:
        return str(definition["$ref"])
    if "anyOf" in definition:
        return "|".join(sorted(_type_of(d) for d in definition["anyOf"]))
    if "enum" in definition:
        return "enum"
    return "any"


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "--check"
    schema = snapshot_schema()
    document = openapi_document()
    functions = function_definitions(document)
    if mode == "--write":
        CONTRACTS.mkdir(parents=True, exist_ok=True)
        if SNAPSHOT.is_file():
            problems = additive_change(json.loads(SNAPSHOT.read_text(encoding="utf-8")), schema)
            if problems:
                print("the snapshot schema is not an additive change of contract v1:")
                print("\n".join(f"  {p}" for p in problems))
                return 1
        SNAPSHOT.write_text(_dump(schema), encoding="utf-8")
        OPENAPI.write_text(_dump(document), encoding="utf-8")
        FUNCTIONS.write_text(_dump(functions), encoding="utf-8")
        print(f"wrote {SNAPSHOT.name}, {OPENAPI.name}, {FUNCTIONS.name} under docs/contracts/")
        return 0
    stale = [
        path.name
        for path, text in (
            (SNAPSHOT, _dump(schema)),
            (OPENAPI, _dump(document)),
            (FUNCTIONS, _dump(functions)),
        )
        if not path.is_file() or path.read_text(encoding="utf-8") != text
    ]
    problems = (
        additive_change(json.loads(SNAPSHOT.read_text(encoding="utf-8")), schema)
        if SNAPSHOT.is_file()
        else []
    )
    if problems:
        print("the snapshot schema is not an additive change of contract v1:")
        print("\n".join(f"  {p}" for p in problems))
    if stale:
        print(f"out of date: {', '.join(stale)}; run python -m scripts.export_contract --write")
    return 1 if stale or problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
