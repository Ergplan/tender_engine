# Stage 7 prompt: completion, Block 0 (safety and capacity)

The owner's completion plan of 2026-10-24 is the prompt for Stage 7 and the stages after
it: `docs/COMPLETION-PLAN.md`, verbatim. Each block is a stage of its own under CLAUDE.md's
rules: a tag at its start, tests with the code, the independent review (rule 15) before
its report, `make deploy`, the report, then stop. Tag `stage-7-start` is `5e84ca6` (the
Stage 6 close); Block 0 runs under it. "Not now" items of the plan (TenderOS, schema v5,
award reviews, public library growth) are not built.

An earlier Stage 7 scope written the same morning (the financial-model page, a results
page, award results into the public library, schema v5) was withdrawn when the plan
arrived; the code written for it was reverted before any commit. What stays from that
morning is what Block 0 asks for: the worker's model registry and its test, the backup,
the review round for `seci-cni-1-700mw`.

## Block 0, read as a stage

- (a) The resize is the owner's step: the commands and the cost go in the report; nothing
  runs before approval.
- (b) `infra/backup.sh`: nightly `pg_dump` and a tar of `/data` on the VM (14 days local),
  copied to a versioned GCS bucket (30-day lifecycle) when `BACKUP_BUCKET` is set and the
  VM's service account may write; a Drive bundle without `.env`. One run now, a restore
  into a scratch database, row counts against live in the report. The bucket and the
  scopes are GCP mutations: the owner's commands, in the report.
- (c) 4 GB swap on the VM; `restart: always` on the app services (the test services stay
  `no`); the cause of the 2026-10-20 start from the journal, and the GCP operations
  command for the owner.
- (d) Every process that opens a session registers every table; a test that fails when any
  entry point's metadata cannot resolve `llm_call_log`'s foreign keys (the exact failure
  of 2026-10-20); the Stage 6 report corrected; the UTC window of the unlogged calls.
