# Block 2 start: the resize hand-over (owner's Cloud Shell step)

The owner's decision of 2026-10-24: the VM stays e2-medium through Block 1; at the start of
Block 2 the build stops and hands over these commands. Target **e2-standard-4** (4 vCPU,
16 GB), with the storage-rw scope change in the same stop. e2-standard-8 only if the Block
2 parser benchmark shows memory pressure or a 400-page scanned tender takes more than 30
minutes, with those numbers shown first.

Downtime: about three minutes (stop, two `set-*` calls, start). Review links keep working
afterwards (the static IP stays). The build agent waits for "done".

## Cost, asia-south2 (Delhi), on demand, 730 h, before any committed-use discount

| Item | e2-medium (today) | e2-standard-4 | e2-standard-8 (only if needed) |
| --- | --- | --- | --- |
| Machine | about USD 30 | about USD 120 (about USD 0.165/h) | about USD 240 |
| 200 GB balanced disk | about USD 24 | unchanged | unchanged |
| Pre-resize snapshot (about 31 GB used) | — | about USD 1/month while kept | — |

Figures from the published rate card as I know it; confirm in the pricing calculator.
Stopping the VM when nobody is reviewing costs only the disk.

## Cloud Shell, in order

```bash
P=tender-intelligence-510607; Z=asia-south2-b; VM=instance-20261004-081207
gcloud config set project $P

# 0. What is there now
gcloud compute instances describe $VM --zone=$Z \
  --format="yaml(machineType,status,serviceAccounts,scheduling,disks[0].source)"

# 1. Snapshot the boot disk first (the rollback)
gcloud compute disks snapshot $VM --zone=$Z \
  --snapshot-names=tender-engine-pre-resize-$(date -u +%Y%m%d) --storage-location=asia-south2

# 2. Stop (about 60 s; the build agent's tmux session dies with it, expected)
gcloud compute instances stop $VM --zone=$Z

# 3. Machine type
gcloud compute instances set-machine-type $VM --zone=$Z --machine-type=e2-standard-4

# 4. Scopes, same stop: storage read-write (the backup bucket), logging and monitoring
#    (the Ops Agent, if re-enabled), the defaults otherwise
gcloud compute instances set-service-account $VM --zone=$Z \
  --service-account=633769690430-compute@developer.gserviceaccount.com \
  --scopes=storage-rw,logging-write,monitoring-write,service-management,service-control,trace

# 5. Start
gcloud compute instances start $VM --zone=$Z

# 6. The VM's own account may now write the bucket; the stop-gap key is retired
gcloud storage buckets add-iam-policy-binding gs://$P-backups \
  --member=serviceAccount:633769690430-compute@developer.gserviceaccount.com \
  --role=roles/storage.objectAdmin
gcloud iam service-accounts keys list --iam-account=tender-backup@$P.iam.gserviceaccount.com
gcloud iam service-accounts keys delete <KEY_ID> --iam-account=tender-backup@$P.iam.gserviceaccount.com
```

## Then, on the VM (the build agent)

- `nproc` and `free -g` show 4 and 15; `docker compose ps` shows the seven services up
  (`restart: always`); `/health` answers.
- The cron line drops `BACKUP_KEY_FILE`; `rm /work/backups/tender-backup-key.json`;
  `make backup` once shows the bucket copy as the VM's own account.
- `make check` once; the check's wall time is recorded in the Block 2 report against the
  33 minutes of e2-medium.
