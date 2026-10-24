# Stage 7, Block 0 report: safety and capacity

Date: 2026-10-24. Prompt: `docs/COMPLETION-PLAN.md` (the owner's plan, verbatim), read as a
stage in `docs/STAGE-7-COMPLETION.md`. Diff: `git diff stage-7-start..HEAD` (tag at
`5e84ca6`, the Stage 6 close). Architecture changes: `docs/ARCHITECTURE.md` ("Operating
the VM", "Stage 7, Block 0"). Decisions: `docs/DECISIONS.md`, 2026-10-24 (three lines).

**Built on the owner's word of 2026-10-24 ("Please fix and complete the application") and
the completion plan that followed the same day. Block 0 is done on the build side: the
worker's model-call logging defect is fixed and held by a test over thirteen entry points;
the nightly backup runs on the VM with a Drive bundle, one run restored into a scratch
database with matching row counts; 4 GB of swap and `restart: always` are in place; the
"reboot" of 2026-10-20 was a clean power-off two days earlier. Two things wait for the
owner: the resize (commands and cost below, nothing run) and the bucket copy of the backup
(the VM's service account may only read Cloud Storage; the commands are below).**

## Definition of done (Block 0 of the plan)

| Item | State | Evidence |
| --- | --- | --- |
| (a) Exact gcloud commands to snapshot and resize to e2-standard-8, with the monthly cost; wait for approval | Commands and cost below; **not run** | this report, "Resize" |
| (b) Nightly `pg_dump` + `/data` on the VM | Done, cron 02:30 UTC | `infra/backup.sh`, `crontab -l`, `/work/backups/backup.log` (two runs today) |
| (b) To a versioned GCS bucket, 30-day retention | Script ready; **blocked** on the service account's scope and on the bucket | `infra/backup.sh` (`BACKUP_BUCKET`), `infra/backup-lifecycle.json`; the owner's commands below |
| (b) A `.env`-stripped copy for Drive | Done | `/work/backups/drive/` (dump, tar, `repo-5e84ca6.tar.gz` from `git archive`, `MANIFEST.sha256`); `tests/scripts/test_backup.py` |
| (b) One run now, a test restore into a scratch DB, row counts against live | Done | "Restore" below |
| (c) 4 GB swap | Done | `/swapfile`, `/etc/fstab`, swappiness 10 (`/etc/sysctl.d/99-tender.conf`) |
| (c) compose `restart=always` | Done for `api`, `worker`, `agent`, `web`, `db`, `caddy`; the test services stay `no` | `docker-compose.yml` |
| (c) Cause of the 20 Oct reboot | Found from the journal; the GCP operations list is the owner's command | "The reboot" below |
| (d) Worker logging defect fixed, with a test that fails when any process can call a model without a committed log row | Done | `worker/main.py`, `scripts/*`, `evals/*`; `tests/worker/test_registry.py` (13 entry points) |
| (d) Stage 6 report corrected; the UTC window | Done | `docs/reports/STAGE-6-REPORT.md`, "Corrected 2026-10-24"; window below |

## (a) Resize: the commands, for the owner's approval

The VM is `instance-20261004-081207` in `asia-south2-b`, machine type `e2-medium` (2 shared
vCPU, 4 GB), one 200 GB balanced persistent disk whose device name is the instance name
(the boot disk; confirm the disk name with the first command). Nothing below has been run.

```bash
# 0. See the disk's name and the instance as they are
gcloud compute instances describe instance-20261004-081207 --zone=asia-south2-b \
  --format="value(machineType.basename(),disks[0].source.basename(),status)"

# 1. Snapshot the disk (the VM may stay up; a stopped VM gives a cleaner snapshot)
gcloud compute disks snapshot instance-20261004-081207 --zone=asia-south2-b \
  --snapshot-names=tender-engine-pre-resize-20261024 --storage-location=asia-south2

# 2. Stop, change the machine type, widen the service account's scopes (both need a stopped VM), start
gcloud compute instances stop instance-20261004-081207 --zone=asia-south2-b
gcloud compute instances set-machine-type instance-20261004-081207 --zone=asia-south2-b \
  --machine-type=e2-standard-8
gcloud compute instances set-service-account instance-20261004-081207 --zone=asia-south2-b \
  --service-account=633769690430-compute@developer.gserviceaccount.com \
  --scopes=storage-rw,logging-write,monitoring-write,service-management,service-control,trace
gcloud compute instances start instance-20261004-081207 --zone=asia-south2-b
```

After the start the six compose services come back by themselves (`restart: always`), the
static IP is unchanged, and `nproc` should print 8. The `tests` watcher stays stopped.

Expected monthly cost, on-demand list prices for asia-south2 (Delhi), 730 hours, before
any committed-use discount; the figures are from the published rate card as I know it and
should be confirmed in the pricing calculator before approval:

| Item | Today (e2-medium) | After (e2-standard-8) |
| --- | --- | --- |
| Machine, on demand | about USD 30 | about USD 240 (about USD 0.33/hour) |
| 200 GB balanced disk | about USD 24 | unchanged |
| Snapshot of about 28 GB used | — | about USD 1 |

A one-year committed-use discount on e2 brings the machine to roughly USD 150 a month;
stopping the VM when nobody is reviewing costs only the disk.

## (b) Backups

**On the VM.** `infra/backup.sh` (`make backup`; cron at 02:30 UTC as the VM user,
`crontab -l`): `pg_dump -Fc` of the app database as the owner role and a tar of `/data`,
under `/work/backups` (mode 700, files 600), kept 14 days by name stamp. Two runs today:

| Run (UTC) | Database | Files |
| --- | --- | --- |
| 2026-10-24 12:18:29 | 83 MB | 1.3 GB |
| 2026-10-24 12:37:42 | 83 MB | 1.3 GB (with the Drive bundle) |

**Restore** of the 12:18 dump into a scratch database `tender_restore` on the same
Postgres (`pg_restore --no-owner --role=tender`, exit 0), then row counts of every table
against live:

| Table | Live | Restored |
| --- | --- | --- |
| candidate | 7,275 | 7,275 |
| evidence_span | 17,445 | 17,445 |
| approval | 1,280 | 1,280 |
| canonical_fact | 1,265 | 1,265 |
| extraction_run | 450 | 450 |
| validation_result | 10,006 | 10,006 |
| page | 4,850 | 4,850 |
| document | 173 | 173 |
| award | 116 | 116 |
| llm_call_log | 1,473 | 1,473 |
| job | 1,618 | 1,618 |
| review_token | 138 | 137 |
| audit_log | 19,808 | 19,807 |
| every other table (22) | equal | equal |

The two differences are the review round opened for `seci-cni-1-700mw` at 12:18:36 UTC
and its audit row, written seven seconds after the dump began. The scratch database is
left in place for the owner to look at (`docker compose exec db psql -U tender -d
tender_restore`); it is dropped by the next Block.

**The Drive bundle** (`/work/backups/drive/`, replaced whole each night): the dump, the
tar, `repo-<commit>.tar.gz` from `git archive HEAD` (tracked files only, so never `.env`,
`infra/allowlist.yaml` or a links file; the script refuses to ship an archive that carries
a `.env`, and `tests/scripts/test_backup.py` checks the tracked set), and
`MANIFEST.sha256`. The owner syncs that folder to Drive with any client (for example
`rclone sync /work/backups/drive gdrive:tender-engine-backups`).

**The bucket.** The script copies the two state files to `gs://$BACKUP_BUCKET/YYYY/MM/`
as the VM's own service account (`gcloud --account=…`); the cron entry already names
`tender-intelligence-510607-backups`. Two things stand in the way, both GCP mutations, the
owner's steps: the instance was created with the `devstorage.read_only` scope (the probe
today: `storage.buckets.list` denied, the bucket "not found"), and the bucket does not
exist. In order:

```bash
# The scopes: step 2 of the resize block above (set-service-account with storage-rw)

# The bucket, versioned, no public access, in the VM's region
gcloud storage buckets create gs://tender-intelligence-510607-backups \
  --project=tender-intelligence-510607 --location=asia-south2 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://tender-intelligence-510607-backups --versioning
# 30 days: live objects deleted after 30 days, earlier versions 30 days after replacement
gcloud storage buckets update gs://tender-intelligence-510607-backups \
  --lifecycle-file=infra/backup-lifecycle.json
# Let the VM's service account write objects
gcloud storage buckets add-iam-policy-binding gs://tender-intelligence-510607-backups \
  --member=serviceAccount:633769690430-compute@developer.gserviceaccount.com \
  --role=roles/storage.objectAdmin

# A daily disk snapshot as well (14 kept), covering the loss of the disk itself
gcloud compute resource-policies create snapshot-schedule tender-engine-daily \
  --region=asia-south2 --max-retention-days=14 --daily-schedule --start-time=22:00 \
  --storage-location=asia-south2
gcloud compute disks add-resource-policies instance-20261004-081207 --zone=asia-south2-b \
  --resource-policies=tender-engine-daily
```

Until then the nightly run ends with `bucket: FAILED (…)` in `/work/backups/backup.log`
and a non-zero exit, after the local files and the Drive bundle are written. Once the
bucket exists, `make backup` once shows the copy.

## (c) Stability

- **Swap**: `/swapfile`, 4 GB, in `/etc/fstab`; `vm.swappiness=10` in
  `/etc/sysctl.d/99-tender.conf`. `free -m` shows it; nothing is swapped yet.
- **Restart**: `restart: always` on the six app services in `docker-compose.yml` (was
  `unless-stopped`, which does not restart a service someone stopped before a reboot).
  Applied by the deploy of this block.
- **The reboot.** The journal has two boots: the first ends at **2026-10-18 22:07:51 UTC**
  with a clean, orderly power-off (`google_guest_agent` received SIGTERM at 22:07:45, the
  metadata script runner ran the "shutdown" event, Docker shut down gracefully, systemd
  reached `poweroff.target`), and the second begins at **2026-10-20 07:49:15 UTC**. No
  out-of-memory kill, no kernel panic, no watchdog: the VM was stopped from the GCP control
  plane (console, `gcloud`, or a scheduled stop) on the evening of 18 October and started
  again on the morning of the 20th, which is also why the tmux session did not survive.
  Who stopped it is in the operations log, which this VM's account cannot read; the owner
  can:

```bash
gcloud compute operations list --project=tender-intelligence-510607 \
  --filter="targetLink~instance-20261004-081207 AND insertTime>2026-10-18" \
  --sort-by=~insertTime --format="table(insertTime,operationType,user,status)"
```

## (d) The worker's model-call logging

**The defect.** `llm_call_log.agent_run_id` has referenced `agent_run` since Stage 5A
(2026-10-18). The API imports the agent package (its routes do), so its metadata resolves
the reference; the worker, the management commands and the eval runner imported
`core.models` and `tender.models` only. In such a process SQLAlchemy cannot sort the
tables at the first flush of a `llm_call_log` row and raises `NoReferencedTableError`,
*after* the model has answered: the call is made, the row is lost, the job fails and is
retried. The Stage 6 import's first run (parse jobs queued 08:46–09:05 UTC on 2026-10-20,
before the importer passed `map_sections=False`) queued one `section_map` job per
publication; all 116 failed that way, four attempts each.

**The window for the Anthropic console: 2026-10-20, 08:54:04 to 09:50:16 UTC, 464 calls
to `claude-fable-5-1`, each a section map of a result PDF (about 10 pages).** Nothing of
them is in `llm_call_log`; the Stage 6 report's "no application model spend" is corrected
in place with that paragraph. At the logged average of earlier section maps (USD 0.24,
on longer documents) the ceiling is about USD 110; the invoice is the figure.

**The fix.** Every entry point imports `agent.models` and `tender.models` (as
`migrations/env.py` always did): `worker/main.py`, `scripts/ingest_tenders.py`,
`scripts/import_results.py`, `scripts/llm_smoke.py`, `scripts/review_token.py`,
`scripts/make_gold.py`, `evals/runner.py`, `evals/report.py`, `evals/feedback_report.py`.

**The test** (`tests/worker/test_registry.py`): thirteen entry points (`worker.main`,
`api.main`, `agent.main`, the seven commands, the four eval modules) are each imported in
a fresh interpreter; the probe then walks `Base.metadata.sorted_tables` and resolves every
foreign key of `llm_call_log`, which is exactly what a flush does, and prints the
registered tables, which must cover every table the migrations created in the test
schema. Run against the worker as it was, the probe fails with `NoReferencedTableError`;
against the fix, thirteen passes. A process that cannot flush a log row cannot pass it.

The 116 failed jobs stay as history (KNOWN-GAPS); no section map is re-run without the
owner's word, since each is a model call.

## Also done in this block

- A review round for `seci-cni-1-700mw` v3, whose amendment of 12 October was validated two
  days before review rounds existed and so never opened one: `python -m
  scripts.review_token round --tender seci-cni-1-700mw --from-version 3` (new command,
  `TokenService.open_round` behind it; `tests/tender/test_rounds.py`). Round 2 for the
  reviewer who completed the review, scoped to v3; the link is in `/work/stage7-links.txt`
  on the VM (mode 600). Block 1(a) asks for it as a round, not a fresh link, and it is.
- Withdrawn: the Stage 7 scope drafted before the plan arrived (financial-model page,
  results page, awards in the public library, schema v5); its code was reverted before
  any commit.

## Tests

New: `tests/worker/test_registry.py` (13 parametrised cases), `tests/scripts/test_backup.py`
(3), `tests/tender/test_rounds.py::test_the_round_command_opens_one_round_and_refuses_a_second`.
Full suite: `.ci/status.json` at the commit (kept as `stage-7-artifacts/ci-status.json`).

## Deployment

TBD-DEPLOY

## Independent review (operating rule 15)

**Not yet run: the reviewer's key has expired.** Run 1 was started at 12:37 UTC on
2026-10-24 (`stage-7-artifacts/review-gpt-6.1-sol-run1.txt`) and the OpenAI API answered
HTTP 401 `expired_secret_key` to the first call. The key in `.env` is the owner's to
replace (as on 2026-10-13); the review then runs as

```bash
git add -A && set -a && . ./.env && set +a && \
  .venv/bin/python -m scripts.independent_review --stage 7 --range stage-7-start \
  --prompt-file docs/STAGE-7-COMPLETION.md > docs/reports/stage-7-artifacts/review-gpt-6.1-sol-run2.txt
```

and its findings, fixes and by-design list replace this paragraph before the block is
closed. Until then this report is a delivery note, not a closed stage: operating rule 15
is not met, and the block stays open on that one point.

## Open questions

- Approval to run the resize block (and with it the scope change), and when: the VM is
  down for about two minutes; review links keep working afterwards.
- Whether the 464 section maps should be re-run now that they would be logged (the PDF
  pane's bookmarks for the awards), at about the same cost again, or left.
- The Drive sync client and folder name the owner prefers.

## Costs

No application model call in this block (`llm_call_log` has no row since 2026-10-18). The
independent review runs on `gpt-6.1-sol`: tokens on the first line of each
`stage-7-artifacts/review-gpt-6.1-sol-runN.txt`.
