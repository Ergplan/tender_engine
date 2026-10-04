"""Management command: keep web/src/api in step with the API.

  python -m scripts.export_openapi --write   regenerate openapi.json and schema.d.ts
  python -m scripts.export_openapi --check   exit 1 if either file is out of date

The UI's only route to the API is the generated client under web/src/api/.
Drift-check idea from tariff-oder packages/contracts/scripts/check-drift.mjs.
"""

import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI

from api.middleware import errors
from api.v1.core import health

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "web" / "src" / "api"
OPENAPI = API_DIR / "openapi.json"
TYPES = API_DIR / "schema.d.ts"
GENERATOR = ROOT / "web" / "node_modules" / "openapi-typescript" / "bin" / "cli.js"


def build_document() -> str:
    """The versioned API only; built without a database connection."""
    app = FastAPI(title="Tender Intelligence Engine", version="0.1.0")
    errors.install(app)
    app.include_router(health.router, prefix="/api/v1")
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def build_types(document_path: Path) -> str:
    done = subprocess.run(
        ["node", str(GENERATOR), str(document_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT / "web",
    )
    if done.returncode != 0:
        raise SystemExit(f"openapi-typescript failed: {done.stderr.strip()}")
    return done.stdout


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "--check"
    document = build_document()
    if mode == "--write":
        OPENAPI.write_text(document, encoding="utf-8")
        TYPES.write_text(build_types(OPENAPI), encoding="utf-8")
        print(f"wrote {OPENAPI.relative_to(ROOT)} and {TYPES.relative_to(ROOT)}")
        return 0
    stale = []
    if not OPENAPI.is_file() or OPENAPI.read_text(encoding="utf-8") != document:
        stale.append(str(OPENAPI.relative_to(ROOT)))
    elif not TYPES.is_file() or TYPES.read_text(encoding="utf-8") != build_types(OPENAPI):
        stale.append(str(TYPES.relative_to(ROOT)))
    if stale:
        print(f"ERROR: out of date: {', '.join(stale)}. Run `make client`.")
        return 1
    print("OpenAPI client is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
