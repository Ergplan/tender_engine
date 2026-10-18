"""The Cloud Run templates and the deploy script parse and name what the runbook says."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLOUDRUN = ROOT / "infra" / "cloudrun"
SERVICES = {
    "service.api.yaml": ("tender-api", "uvicorn"),
    "service.api-product.yaml": ("tender-api-product", "uvicorn"),
    "service.worker.yaml": ("tender-worker", "worker.main"),
    "service.agent.yaml": ("tender-agent", "agent.main"),
    "service.web.yaml": ("tender-web", None),
}
SECRETS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DATABASE_URL",
    "ADMIN_TOKEN",
    "SESSION_SECRET",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
)


def _env(container: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    return {item["name"]: item for item in container.get("env", [])}


def test_every_service_template_parses_with_its_name_command_and_settings() -> None:
    for filename, (name, command_word) in SERVICES.items():
        doc = yaml.safe_load((CLOUDRUN / filename).read_text())
        assert doc["kind"] == "Service" and doc["metadata"]["name"] == name, filename
        container = doc["spec"]["template"]["spec"]["containers"][0]
        assert "[IMAGE" in container["image"], filename
        if command_word:
            assert any(command_word in part for part in container["args"]), filename
            env = _env(container)
            for secret in SECRETS:
                assert secret in env and "valueFrom" in env[secret], (filename, secret)
            assert env["STORAGE_BACKEND"]["value"] == "gcs"
            assert "GCS_BUCKET" in env and "PRODUCT" in env
            annotations = doc["spec"]["template"]["metadata"]["annotations"]
            assert "run.googleapis.com/cloudsql-instances" in annotations
    api_env = _env(
        yaml.safe_load((CLOUDRUN / "service.api-product.yaml").read_text())["spec"]["template"][
            "spec"
        ]["containers"][0]
    )
    assert api_env["PRODUCT"]["value"] == "api"
    worker = yaml.safe_load((CLOUDRUN / "service.worker.yaml").read_text())
    annotations = worker["spec"]["template"]["metadata"]["annotations"]
    assert annotations["autoscaling.knative.dev/minScale"] == "1"
    assert annotations["run.googleapis.com/cpu-throttling"] == "false"


def test_the_migration_job_runs_alembic_as_the_owner() -> None:
    job = yaml.safe_load((CLOUDRUN / "job.migrate.yaml").read_text())
    assert job["kind"] == "Job" and job["metadata"]["name"] == "tender-migrate"
    container = job["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]
    assert "alembic" in " ".join(container["args"])
    assert "MIGRATION_DATABASE_URL" in _env(container)


def test_the_deploy_script_parses_and_the_runbook_names_every_step() -> None:
    subprocess.run(["bash", "-n", str(CLOUDRUN / "deploy.sh")], check=True)
    printed = subprocess.run(
        ["bash", str(CLOUDRUN / "deploy.sh"), "--print-only"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout
    assert "gcloud run services replace" in printed and "gcloud run jobs replace" in printed
    readme = (CLOUDRUN / "README.md").read_text()
    for step in (
        "services enable",
        "artifacts repositories create",
        "builds submit",
        "sql instances create",
        "storage buckets create",
        "secrets create",
        "run jobs",
        "run services",
        "compute network-endpoint-groups create",
        "compute url-maps",
        "compute ssl-certificates create",
        "compute security-policies",
        "auth/callback",
        # Without this mark every request through the load balancer would count as internal.
        '--custom-request-header "X-Public-Request:1"',
    ):
        assert step in readme, step
