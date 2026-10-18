#!/usr/bin/env bash
# Renders the Cloud Run templates in this folder and applies them. Run by the operator
# after the one-time setup in README.md (needs gcloud logged in with run.admin on the
# project; the build agent on the VM never runs it).
#
# Usage: infra/cloudrun/deploy.sh [--print-only] [--only api,worker,agent,web,api-product,migrate]
#   --print-only   print the gcloud commands instead of running them
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${GCP_PROJECT:-tender-intelligence-510607}"
REGION="${GCP_REGION:-asia-south2}"
REPO="${AR_REPO:-tender-engine}"
TAG="${IMAGE_TAG:-$(git -C "$HERE/../.." rev-parse --short HEAD 2>/dev/null || echo latest)}"
IMAGE_PYTHON="${IMAGE_PYTHON:-${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/python:${TAG}}"
IMAGE_WEB="${IMAGE_WEB:-${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/web:${TAG}}"
SQL_CONNECTION="${SQL_CONNECTION:-${PROJECT}:${REGION}:tender-sql}"
BUCKET="${GCS_BUCKET:-tender-engine-data-${PROJECT}}"

PRINT_ONLY=0
ONLY="api,worker,agent,web,api-product,migrate"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --print-only) PRINT_ONLY=1 ;;
    --only) ONLY="$2"; shift ;;
    *) echo "unknown argument: $1"; exit 1 ;;
  esac
  shift
done

render() {
  sed -e "s|\[PROJECT\]|${PROJECT}|g" \
      -e "s|\[REGION\]|${REGION}|g" \
      -e "s|\[IMAGE_PYTHON\]|${IMAGE_PYTHON}|g" \
      -e "s|\[IMAGE_WEB\]|${IMAGE_WEB}|g" \
      -e "s|\[SQL_CONNECTION\]|${SQL_CONNECTION}|g" \
      -e "s|\[BUCKET\]|${BUCKET}|g" \
      "$1"
}

run() {
  if [[ "$PRINT_ONLY" == 1 ]]; then echo "$*"; else "$@"; fi
}

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

wanted() { [[ ",$ONLY," == *",$1,"* ]]; }

if wanted migrate; then
  render "$HERE/job.migrate.yaml" > "$OUT/job.migrate.yaml"
  run gcloud run jobs replace "$OUT/job.migrate.yaml" --project "$PROJECT" --region "$REGION"
  run gcloud run jobs execute tender-migrate --project "$PROJECT" --region "$REGION" --wait
fi

for name in api api-product worker agent web; do
  wanted "$name" || continue
  render "$HERE/service.${name}.yaml" > "$OUT/service.${name}.yaml"
  run gcloud run services replace "$OUT/service.${name}.yaml" --project "$PROJECT" --region "$REGION"
done

if [[ "$PRINT_ONLY" == 1 ]]; then
  echo "# rendered with IMAGE_PYTHON=${IMAGE_PYTHON} IMAGE_WEB=${IMAGE_WEB} SQL=${SQL_CONNECTION} BUCKET=${BUCKET}"
fi
