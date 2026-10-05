"""Continuous test pipeline. Runs every check and writes .ci/status.json and .ci/latest.log.

  python infra/ci/run_checks.py --once    run all checks once; exit 1 if any is red
  python infra/ci/run_checks.py --watch   run once, then again on every save

status.json has one entry per check: name, status (pass/fail), duration_s and the first
failing message. Claude Code and infra/hooks/pre-commit read it before every commit.
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_DIR = ROOT / ".ci"
WEB = ROOT / "web"
PY_PACKAGES = ("core", "tender", "api", "worker")
WATCH_DIRS = (*PY_PACKAGES, "tests", "scripts", "migrations", "infra/ci", "web/src")
WATCH_FILES = ("pyproject.toml", "alembic.ini", "web/package.json", "web/tsconfig.json")
WATCH_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".ini", ".ts", ".tsx", ".json", ".css"}
CI_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://tender:tender@db:5432/tender_ci"
)
NODE_BIN = WEB / "node_modules"


@dataclass(frozen=True)
class Check:
    name: str
    commands: tuple[tuple[str, ...], ...]
    cwd: Path = ROOT


def checks() -> list[Check]:
    py = sys.executable
    return [
        Check("ruff_check", ((py, "-m", "ruff", "check", "."),)),
        Check("ruff_format", ((py, "-m", "ruff", "format", "--check", "."),)),
        Check("mypy", ((py, "-m", "mypy"),)),
        Check(
            "alembic_check",
            ((py, "-m", "alembic", "upgrade", "head"), (py, "-m", "alembic", "check")),
        ),
        Check("pytest", ((py, "-m", "pytest", "-p", "no:cacheprovider"),)),
        Check("openapi_drift", ((py, "-m", "scripts.export_openapi", "--check"),)),
        Check("field_trace", ((py, "-m", "scripts.gen_field_trace", "--check"),)),
        Check("tsc", (("node", str(NODE_BIN / "typescript/bin/tsc"), "--noEmit"),), WEB),
        Check("vitest", (("node", str(NODE_BIN / "vitest/vitest.mjs"), "run"),), WEB),
    ]


def run_command(command: tuple[str, ...], cwd: Path) -> tuple[int, str]:
    env = {**os.environ, "DATABASE_URL": CI_DATABASE_URL, "NO_COLOR": "1", "CI": "1"}
    env.pop("DB_SCHEMA", None)
    try:
        done = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, timeout=900, check=False
        )
    except FileNotFoundError as exc:
        return 127, f"{exc}"
    except subprocess.TimeoutExpired:
        return 124, "timed out after 900 s"
    return done.returncode, (done.stdout + done.stderr)


def first_failure(output: str) -> str:
    """The most specific failing line: a named failed test, then an error line, then the tail."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for prefixes in (("FAILED ", "ERROR "), ("E  ",), ("error", "Error", "FAIL", "×")):
        for line in lines:
            if line.startswith(prefixes) or (prefixes[0] == "error" and ": error" in line):
                return line[:300]
    for line in lines:
        if "would reformat" in line or "error" in line.lower():
            return line[:300]
    return lines[-1][:300] if lines else "no output"


def run_all(trigger: list[str]) -> bool:
    CI_DIR.mkdir(exist_ok=True)
    started = time.time()
    write_status({"state": "running", "started_at": started, "trigger": trigger, "checks": []})
    results: list[dict[str, object]] = []
    log_parts: list[str] = []
    for check in checks():
        check_started = time.time()
        code, output = 0, ""
        for command in check.commands:
            code, piece = run_command(command, check.cwd)
            output += f"$ {' '.join(command)}\n{piece}\n"
            if code != 0:
                break
        passed = code == 0
        results.append(
            {
                "name": check.name,
                "status": "pass" if passed else "fail",
                "duration_s": round(time.time() - check_started, 1),
                "first_failure": None if passed else first_failure(output),
            }
        )
        log_parts.append(f"===== {check.name}: {'pass' if passed else 'FAIL'} =====\n{output}")
        print(f"{'pass' if passed else 'FAIL'}  {check.name}", flush=True)
    ok = all(result["status"] == "pass" for result in results)
    (CI_DIR / "latest.log").write_text("\n".join(log_parts), encoding="utf-8")
    write_status(
        {
            "state": "done",
            "ok": ok,
            "started_at": started,
            "finished_at": time.time(),
            "trigger": trigger,
            "checks": results,
        }
    )
    print(f"--- {'GREEN' if ok else 'RED'} in {time.time() - started:.0f}s", flush=True)
    return ok


def write_status(status: dict[str, object]) -> None:
    tmp = CI_DIR / "status.json.tmp"
    tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
    tmp.replace(CI_DIR / "status.json")


def scoped_pytest(changed: list[str]) -> None:
    """Fast signal first: run the tests of the packages that changed, before the full run."""
    packages = sorted({path.split("/")[0] for path in changed} & set(PY_PACKAGES))
    targets = [f"tests/{package}" for package in packages if (ROOT / "tests" / package).is_dir()]
    if not targets:
        return
    command = (sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-x", *targets)
    code, output = run_command(command, ROOT)
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    verdict = "pass" if code == 0 else "FAIL"
    print(f"scoped pytest {' '.join(targets)}: {verdict} {tail}", flush=True)


def watched_files() -> list[Path]:
    files = [ROOT / f for f in WATCH_FILES if (ROOT / f).is_file()]
    for directory in WATCH_DIRS:
        files += [
            path
            for path in (ROOT / directory).rglob("*")
            if path.suffix in WATCH_SUFFIXES and path.is_file() and "__pycache__" not in path.parts
        ]
    return files


def run_until_current(trigger: list[str]) -> None:
    """Run all checks; repeat while any watched file was saved after the run started."""
    while True:
        started = time.time()
        run_all(trigger)
        late = sorted(
            str(path.relative_to(ROOT))
            for path in watched_files()
            if path.stat().st_mtime > started
        )
        if not late:
            return
        print(f"saved during the run: {', '.join(late[:8])}", flush=True)
        trigger = late


def watch() -> None:
    from watchfiles import watch as watch_paths

    run_until_current(["startup"])
    paths = [ROOT / d for d in WATCH_DIRS if (ROOT / d).exists()]
    paths += [ROOT / f for f in WATCH_FILES if (ROOT / f).exists()]
    for changes in watch_paths(*paths, debounce=1500, step=200):
        changed = sorted(
            {
                str(Path(path).relative_to(ROOT))
                for _, path in changes
                if Path(path).suffix in WATCH_SUFFIXES and "__pycache__" not in path
            }
        )
        if not changed:
            continue
        print(f"changed: {', '.join(changed[:8])}", flush=True)
        scoped_pytest(changed)
        run_until_current(changed)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--once"
    if mode == "--watch":
        watch()
        return 0
    return 0 if run_all(["manual"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
