"""The contract files (Stage 7, Block 6 a and d): the snapshot schema is an additive change
of the committed contract v1, the OpenAPI document covers the caller's routes, and the
function definitions carry every parameter."""

import json

from scripts.export_contract import (
    FUNCTIONS,
    OPENAPI,
    SNAPSHOT,
    additive_change,
    function_definitions,
    openapi_document,
    snapshot_schema,
)


def test_the_committed_snapshot_contract_is_kept_additively() -> None:
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert additive_change(committed, snapshot_schema()) == []
    assert committed["properties"]["contract_version"]["default"] == "1"
    field = committed["$defs"]["SnapshotField"]
    assert {"path", "state", "source", "value", "confidence", "version_no", "evidence"} <= set(
        field["properties"]
    )


def test_additive_change_names_what_a_breaking_change_takes_away() -> None:
    old = {
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a"],
        "$defs": {"F": {"properties": {"x": {"type": "string"}}, "required": []}},
    }
    same_plus = {
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}, "c": {"type": "string"}},
        "required": ["a"],
        "$defs": {
            "F": {"properties": {"x": {"type": "string"}, "y": {"type": "string"}}, "required": []}
        },
    }
    assert additive_change(old, same_plus) == []
    broken = {
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
        "$defs": {"F": {"properties": {"x": {"type": "string"}}, "required": ["x"]}},
    }
    assert additive_change(old, broken) == [
        "snapshot.a: type string became integer",
        "snapshot.b: removed",
        "F.x: became required",
    ]
    assert additive_change(old, {"properties": {}, "required": []}) == [
        "snapshot.a: removed",
        "snapshot.b: removed",
        "F: definition removed",
    ]


def test_openapi_and_functions_cover_the_callers_routes() -> None:
    document = openapi_document()
    assert document["openapi"].startswith("3.1")
    paths = set(document["paths"])
    for path in (
        "/api/v1/tenders/submit",
        "/api/v1/tenders/{tender_id}/submit-amendment",
        "/api/v1/tenders/{tender_id}/status",
        "/api/v1/tenders/{tender_id}/fields",
        "/api/v1/tenders/{tender_id}/changes",
        "/api/v1/tenders/{tender_id}/ask",
        "/api/v1/tenders/{tender_id}/review-link",
        "/api/v1/webhooks",
    ):
        assert path in paths, path
    assert "ApiKey" in document["components"]["securitySchemes"]
    functions = {f["name"]: f for f in function_definitions(document)}
    submit = functions["submit_tender"]
    assert submit["x-method"] == "POST" and submit["x-path"] == "/api/v1/tenders/submit"
    assert {"source_url", "tender_type", "file"} <= set(submit["parameters"]["properties"])
    assert submit["parameters"]["properties"]["file"]["type"] == "string"
    status = functions["get_status"]
    assert status["parameters"]["required"] == ["tender_id"]
    ask = functions["ask_tender"]
    assert ask["parameters"]["required"] == ["question", "tender_id"]
    committed = json.loads(FUNCTIONS.read_text(encoding="utf-8"))
    assert {f["name"] for f in committed} == set(functions)
    assert json.loads(OPENAPI.read_text(encoding="utf-8"))["info"]["version"] == "1.0.0"
