# Cloud Run deployment: the operator's runbook (Stage 5C)

Every step below is a command the operator pastes with the `!` prefix in the build
session (or runs from Cloud Shell as a project owner). The build agent prepares them and
never runs a GCP mutation itself. Placeholders: `[YOUR DOMAIN]` (a domain you control,
pointed at the load balancer's address in step 9), `[REVIEWER_CIDRS]` and `[ADMIN_CIDRS]`
(from `infra/allowlist.yaml`), `[ANTHROPIC_KEY]`, `[OPENAI_KEY]`, `[PW_OWNER]`, `[PW_APP]`,
`[ADMIN_TOKEN]`, `[SESSION_SECRET]`, `[OIDC_CLIENT_ID]`, `[OIDC_CLIENT_SECRET]`. Secrets go
to Secret Manager only; never into the repo or a shell history you keep.

`docker compose` on the VM stays for local development and the current review phase.

```bash
export PROJECT=tender-intelligence-510607 REGION=asia-south2 REPO=tender-engine
export SQL=tender-sql BUCKET=tender-engine-data-$PROJECT
export IMAGE_PYTHON=$REGION-docker.pkg.dev/$PROJECT/$REPO/python:$(git rev-parse --short HEAD)
export IMAGE_WEB=$REGION-docker.pkg.dev/$PROJECT/$REPO/web:$(git rev-parse --short HEAD)
```

## 1. APIs and the service account

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com compute.googleapis.com storage.googleapis.com --project $PROJECT
gcloud iam service-accounts create tender-run --display-name "Tender engine Cloud Run" --project $PROJECT
gcloud projects add-iam-policy-binding $PROJECT --member serviceAccount:tender-run@$PROJECT.iam.gserviceaccount.com --role roles/cloudsql.client
gcloud projects add-iam-policy-binding $PROJECT --member serviceAccount:tender-run@$PROJECT.iam.gserviceaccount.com --role roles/secretmanager.secretAccessor
```

## 2. Images: Artifact Registry and Cloud Build

```bash
gcloud artifacts repositories create $REPO --repository-format docker --location $REGION --project $PROJECT
gcloud builds submit --project $PROJECT --tag $IMAGE_PYTHON --config /dev/null . 2>/dev/null || gcloud builds submit --project $PROJECT . --substitutions _IMAGE=$IMAGE_PYTHON --config infra/cloudrun/cloudbuild.python.yaml
gcloud builds submit --project $PROJECT . --substitutions _IMAGE=$IMAGE_WEB --config infra/cloudrun/cloudbuild.web.yaml
```

(`cloudbuild.python.yaml` builds `infra/docker/Dockerfile.python` target `prod`;
`cloudbuild.web.yaml` builds `infra/docker/Dockerfile.web.prod`.)

## 3. Cloud SQL: Postgres 16, the owner and the app role

```bash
gcloud sql instances create $SQL --database-version POSTGRES_16 --tier db-custom-2-7680 --region $REGION --storage-auto-increase --project $PROJECT
gcloud sql databases create tender --instance $SQL --project $PROJECT
gcloud sql users create tender --instance $SQL --password '[PW_OWNER]' --project $PROJECT
gcloud sql users create tender_app --instance $SQL --password '[PW_APP]' --project $PROJECT
gcloud sql connect $SQL --user tender --database tender --project $PROJECT
```

In the `psql` that opens: `GRANT CONNECT ON DATABASE tender TO tender_app;` then `\q`.
Migration 0018 (run by the job in step 7) grants `tender_app` the table privileges; the
role has no ownership, so row-level security binds it.

## 4. The bucket

```bash
gcloud storage buckets create gs://$BUCKET --location $REGION --uniform-bucket-level-access --project $PROJECT
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member serviceAccount:tender-run@$PROJECT.iam.gserviceaccount.com --role roles/storage.objectAdmin
gcloud storage rsync -r /data gs://$BUCKET
```

(The last line copies the VM's `/data` — the stored PDFs and page renders — into the
bucket; run it from the VM. The database follows with a `pg_dump` of the VM's `tender`
database restored into Cloud SQL: `gcloud sql import sql` from a dump uploaded to the
bucket.)

## 5. Secrets

```bash
for s in ANTHROPIC_API_KEY OPENAI_API_KEY DATABASE_URL MIGRATION_DATABASE_URL ADMIN_TOKEN SESSION_SECRET OIDC_CLIENT_ID OIDC_CLIENT_SECRET; do gcloud secrets create $s --replication-policy automatic --project $PROJECT; done
printf '%s' '[ANTHROPIC_KEY]' | gcloud secrets versions add ANTHROPIC_API_KEY --data-file - --project $PROJECT
printf '%s' '[OPENAI_KEY]' | gcloud secrets versions add OPENAI_API_KEY --data-file - --project $PROJECT
printf '%s' "postgresql+psycopg://tender_app:[PW_APP]@/tender?host=/cloudsql/$PROJECT:$REGION:$SQL" | gcloud secrets versions add DATABASE_URL --data-file - --project $PROJECT
printf '%s' "postgresql+psycopg://tender:[PW_OWNER]@/tender?host=/cloudsql/$PROJECT:$REGION:$SQL" | gcloud secrets versions add MIGRATION_DATABASE_URL --data-file - --project $PROJECT
printf '%s' '[ADMIN_TOKEN]' | gcloud secrets versions add ADMIN_TOKEN --data-file - --project $PROJECT
printf '%s' '[SESSION_SECRET]' | gcloud secrets versions add SESSION_SECRET --data-file - --project $PROJECT
printf '%s' '[OIDC_CLIENT_ID]' | gcloud secrets versions add OIDC_CLIENT_ID --data-file - --project $PROJECT
printf '%s' '[OIDC_CLIENT_SECRET]' | gcloud secrets versions add OIDC_CLIENT_SECRET --data-file - --project $PROJECT
```

## 6. The OIDC client

In Google Cloud Console → APIs & Services → Credentials: create an OAuth client of type
Web application, authorised redirect URI `https://[YOUR DOMAIN]/api/v1/auth/callback`
(and `https://api.[YOUR DOMAIN]/api/v1/auth/callback` if the API product signs in
too). Put its id and secret into the two secrets of step 5.

## 7. The migration job, then the services

```bash
infra/cloudrun/deploy.sh --print-only
infra/cloudrun/deploy.sh --only migrate
infra/cloudrun/deploy.sh --only api,api-product,worker,agent,web
```

`deploy.sh` renders `job.migrate.yaml` and the five `service.*.yaml` with the project,
region, images, Cloud SQL connection and bucket, then `gcloud run jobs replace` /
`gcloud run jobs execute` (the migrations as the owner) and `gcloud run services replace`
for each service. `tender-worker` and `tender-agent` run with one instance always on and
the CPU always allocated; `tender-api` and `tender-api-product` autoscale from one; the
web bundle from zero.

## 8. Serverless NEGs, the load balancer, the certificate

```bash
gcloud compute network-endpoint-groups create neg-tender-api --region $REGION --network-endpoint-type serverless --cloud-run-service tender-api --project $PROJECT
gcloud compute network-endpoint-groups create neg-tender-api-product --region $REGION --network-endpoint-type serverless --cloud-run-service tender-api-product --project $PROJECT
gcloud compute network-endpoint-groups create neg-tender-web --region $REGION --network-endpoint-type serverless --cloud-run-service tender-web --project $PROJECT
for b in api api-product web; do gcloud compute backend-services create be-tender-$b --global --load-balancing-scheme EXTERNAL_MANAGED --project $PROJECT; gcloud compute backend-services add-backend be-tender-$b --global --network-endpoint-group neg-tender-$b --network-endpoint-group-region $REGION --project $PROJECT; done
# Every request that comes through the load balancer is marked as public, as Caddy marks it on
# the VM: without this header the API would treat requests from outside as internal and admit
# them without a sign-in, a review link or an API key. Do not skip this line.
for b in api api-product; do gcloud compute backend-services update be-tender-$b --global --custom-request-header "X-Public-Request:1" --project $PROJECT; done
gcloud compute url-maps create tender-lb --default-service be-tender-web --project $PROJECT
gcloud compute url-maps add-path-matcher tender-lb --path-matcher-name app --default-service be-tender-web --path-rules "/api/*=be-tender-api,/files/*=be-tender-api,/health=be-tender-api" --new-hosts "[YOUR DOMAIN]" --project $PROJECT
gcloud compute url-maps add-path-matcher tender-lb --path-matcher-name api-product --default-service be-tender-api-product --new-hosts "api.[YOUR DOMAIN]" --project $PROJECT
gcloud compute ssl-certificates create tender-cert --domains "[YOUR DOMAIN],api.[YOUR DOMAIN]" --global --project $PROJECT
gcloud compute target-https-proxies create tender-https --url-map tender-lb --ssl-certificates tender-cert --project $PROJECT
gcloud compute addresses create tender-lb-ip --global --project $PROJECT
gcloud compute forwarding-rules create tender-https-rule --global --load-balancing-scheme EXTERNAL_MANAGED --address tender-lb-ip --target-https-proxy tender-https --ports 443 --project $PROJECT
gcloud compute addresses describe tender-lb-ip --global --format 'value(address)' --project $PROJECT
```

Point `[YOUR DOMAIN]` and `api.[YOUR DOMAIN]` at the printed address; the managed
certificate turns ACTIVE once DNS resolves (up to an hour).

## 9. Cloud Armor in place of the VM firewall

```bash
gcloud compute security-policies create tender-allowlist --description "reviewers and admins" --project $PROJECT
gcloud compute security-policies rules create 1000 --security-policy tender-allowlist --src-ip-ranges "[REVIEWER_CIDRS],[ADMIN_CIDRS]" --action allow --project $PROJECT
gcloud compute security-policies rules update 2147483647 --security-policy tender-allowlist --action deny-403 --project $PROJECT
gcloud compute backend-services update be-tender-web --security-policy tender-allowlist --global --project $PROJECT
gcloud compute backend-services update be-tender-api --security-policy tender-allowlist --global --project $PROJECT
```

The API product (`be-tender-api-product`) is reached with API keys and is left open to
the internet by design; attach the same policy if its clients come from known ranges.
`infra/allowlist.yaml` stays the single list of reviewer and admin ranges: edit it, then
rerun the `rules create` line with the new ranges (or `rules update 1000`).

## 10. Cutover

1. Set `PUBLIC_BASE_URL` in `service.api.yaml` to `https://[YOUR DOMAIN]` (already the
   placeholder) and redeploy: `infra/cloudrun/deploy.sh --only api`.
2. Register the redirect URI `https://[YOUR DOMAIN]/api/v1/auth/callback` on the OIDC
   client (step 6) if not done.
3. Restore the database dump into Cloud SQL and sync `/data` to the bucket (step 4), then
   run the migration job once more (`deploy.sh --only migrate`).
4. Open `https://[YOUR DOMAIN]/health`, sign in, open a review link; then stop the VM's
   `caddy` (`docker compose stop caddy`) so the old address no longer serves.

## Rolling out a new build

```bash
gcloud builds submit --project $PROJECT . --substitutions _IMAGE=$IMAGE_PYTHON --config infra/cloudrun/cloudbuild.python.yaml
gcloud builds submit --project $PROJECT . --substitutions _IMAGE=$IMAGE_WEB --config infra/cloudrun/cloudbuild.web.yaml
infra/cloudrun/deploy.sh
```
