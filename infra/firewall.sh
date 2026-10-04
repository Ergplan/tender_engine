#!/usr/bin/env bash
# Recreates the tender-engine firewall rules from infra/allowlist.yaml.
# Adding a reviewer later: edit infra/allowlist.yaml, run this script.
#
# Needs gcloud with compute permissions (the VM's default service account
# does not have them; run from Cloud Shell or any gcloud logged in as a
# project owner/editor).
#
# Usage: infra/firewall.sh [--print-only]
#   --print-only   print the gcloud commands instead of running them
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ALLOWLIST="${ALLOWLIST:-$HERE/allowlist.yaml}"
PROJECT="${GCP_PROJECT:-tender-intelligence-510607}"
ZONE="${GCP_ZONE:-asia-south2-b}"
INSTANCE="${GCP_INSTANCE:-instance-20261004-081207}"
NETWORK="${GCP_NETWORK:-default}"
TAG="tender-engine"

PRINT_ONLY=0
[[ "${1:-}" == "--print-only" ]] && PRINT_ONLY=1

[[ -f "$ALLOWLIST" ]] || { echo "missing $ALLOWLIST (copy allowlist.example.yaml)"; exit 1; }

# Minimal YAML list parser: top-level "key:" then "  - value  # comment".
# Bare IPv4 addresses become /32.
read_list() {
  awk -v key="$1" '
    /^[A-Za-z_]+:/ { in_key = ($0 ~ "^" key ":") ; next }
    in_key && /^[[:space:]]*-[[:space:]]*/ {
      sub(/^[[:space:]]*-[[:space:]]*/, ""); sub(/[[:space:]]*#.*$/, ""); gsub(/["'"'"']/, "")
      if ($0 != "") print
    }' "$ALLOWLIST" \
  | while read -r cidr; do
      if [[ "$cidr" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then echo "$cidr/32"; else echo "$cidr"; fi
    done
}

join() { local IFS=,; echo "$*"; }

mapfile -t REVIEWERS < <(read_list reviewers)
mapfile -t ADMINS < <(read_list admins)

[[ ${#ADMINS[@]} -gt 0 ]] || { echo "admins list is empty; refusing (would lock out SSH)"; exit 1; }
[[ ${#REVIEWERS[@]} -gt 0 ]] || echo "warning: reviewers list is empty; only admins will reach 443"

HTTPS_RANGES="$(join "${REVIEWERS[@]}" "${ADMINS[@]}")"
SSH_RANGES="$(join "${ADMINS[@]}")"

run() { if (( PRINT_ONLY )); then printf "%q " "$@"; echo; else printf "+ "; printf "%q " "$@"; echo; "$@"; fi; }

rule_exists() { gcloud compute firewall-rules describe "$1" --project "$PROJECT" >/dev/null 2>&1; }

upsert_rule() {  # name port ranges
  local name="$1" port="$2" ranges="$3"
  if (( ! PRINT_ONLY )) && rule_exists "$name"; then
    run gcloud compute firewall-rules update "$name" --project "$PROJECT" \
      --source-ranges="$ranges" --rules="tcp:$port"
  else
    run gcloud compute firewall-rules create "$name" --project "$PROJECT" --network "$NETWORK" \
      --direction=INGRESS --action=ALLOW --rules="tcp:$port" \
      --source-ranges="$ranges" --target-tags="$TAG" --description="tender-engine: tcp:$port from allowlist"
  fi
}

echo "project=$PROJECT zone=$ZONE instance=$INSTANCE"
echo "443 <- $HTTPS_RANGES"
echo "22  <- $SSH_RANGES"

run gcloud compute instances add-tags "$INSTANCE" --project "$PROJECT" --zone "$ZONE" --tags="$TAG"
upsert_rule tender-engine-https 443 "$HTTPS_RANGES"
upsert_rule tender-engine-ssh   22  "$SSH_RANGES"

# Default rules on the default network open 22 (and sometimes 443) to the
# whole internet for every instance, which includes this one. Remove them
# last, after the allowlisted rules exist.
for r in default-allow-ssh default-allow-https; do
  if (( PRINT_ONLY )); then
    echo "gcloud compute firewall-rules delete $r --project $PROJECT --quiet  # if it exists"
  elif rule_exists "$r"; then
    run gcloud compute firewall-rules delete "$r" --project "$PROJECT" --quiet
  fi
done

if (( ! PRINT_ONLY )); then
  echo; echo "Resulting rules targeting tag $TAG:"
  gcloud compute firewall-rules list --project "$PROJECT" --filter="targetTags.list():$TAG" \
    --format="table(name,direction,sourceRanges.list(),allowed[].map().firewall_rule().list(),targetTags.list())"
fi
