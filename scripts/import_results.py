"""Management command: import award results from the RE-tender-results dataset (Stage 6).

  python -m scripts.import_results --root /work/ref/RE-tender-results [--only <source id> ...]
      [--report-json <path>]

Run once per dataset commit; safe to repeat (a publication already imported from the same
sha256 is skipped). Every source host must be on infra/source-domains.yaml or nothing is
imported; every file's sha256 must equal the dataset's or the import stops there. No model
is called. The report lists what was imported, skipped and left out, the evidence located
per field, and the tenders the publications were linked to.
"""

import argparse
import json
import sys
from pathlib import Path

import agent.models  # noqa: F401  (registers the agent pass tables on Base.metadata)
import tender.models  # noqa: F401  (registers the tender tables on Base.metadata)
from core.config import Settings
from core.db import make_engine, make_session_factory
from core.llm.client import LLMClient
from core.services.extract import ExtractService
from core.services.ingest import IngestService
from core.services.parse import ParseService
from core.services.validate import ValidationService
from core.storage import make_storage
from tender.services.packs import build_registry
from tender.services.results_import import (
    ACTOR,
    Dataset,
    ImportReport,
    ResultsImporter,
    ResultsImportError,
)
from tender.services.source_domains import SourceAllowlist


def build_importer(settings: Settings) -> tuple[ResultsImporter, object]:
    session_factory = make_session_factory(make_engine(settings), settings.tenant_id)
    storage = make_storage(settings)
    schemas, catalog = build_registry()
    # The extract service needs the client only to construct; the import makes no call.
    llm = LLMClient(settings, session_factory, prompt_roots=catalog.prompt_roots)
    extract = ExtractService(llm, storage, schemas, settings)
    importer = ResultsImporter(
        ingest=IngestService(storage, settings.tenant_id),
        parse=ParseService(storage, settings),
        extract=extract,
        validate=ValidationService(schemas, settings.tenant_id),
        catalog=catalog,
        allowlist=SourceAllowlist.load(),
        tenant_id=settings.tenant_id,
    )
    return importer, session_factory


def run(
    settings: Settings, root: Path, only: list[str] | None, report_json: Path | None
) -> ImportReport:
    importer, session_factory = build_importer(settings)
    dataset = Dataset(root)
    with session_factory() as session:  # type: ignore[operator]
        report = importer.run(session, dataset, created_by=ACTOR, only=only or None)
    if report_json is not None:
        report_json.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="import_results", description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="the dataset clone")
    parser.add_argument("--only", nargs="*", help="source ids to import, else every PDF source")
    parser.add_argument("--report-json", type=Path, help="write the report as JSON here")
    args = parser.parse_args(argv[1:])
    try:
        report = run(Settings(), args.root, args.only, args.report_json)
    except ResultsImportError as exc:
        print(f"import stopped: {exc}")
        return 1
    print("\n".join(report.lines()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
