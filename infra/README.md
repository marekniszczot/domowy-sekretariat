# infra

Terraform for everything inside the GCP project: APIs, letters bucket (30-day lifecycle),
Firestore, Document AI OCR processor, Secret Manager, Artifact Registry, Cloud Run
service `web` and job `jobs`, Cloud Tasks queue, Cloud Scheduler, budget, and two
GitHub Actions identities via Workload Identity Federation.

## Bootstrap (once)

The project and its billing link are created by hand, because Terraform needs an
existing project for its state bucket:

```sh
gcloud projects create <project-id> [--organization=<org-id>]
gcloud billing projects link <project-id> --billing-account=<billing-account-id>
GCLOUD_CONFIGURATION=<config> infra/bootstrap.sh <project-id> europe-central2
cp infra/terraform.tfvars.example infra/terraform.tfvars   # fill in
```

Sign in with Google needs an OAuth client, which Terraform cannot create. In the
console (Google Auth Platform): configure the consent screen (External, testing mode,
household members' Google accounts as test users), then create a client of type
*Web application* with the service URL as JavaScript origin and
`<service URL>/auth/google` as redirect URI. Put its client id and the service URL
into `terraform.tfvars` (`google_client_id`, `web_base_url`).

Reminders are sent from a mailbox in your own domain over SMTP with implicit TLS
(port 465): put its server and address into `smtp_host` and `smtp_user`. Add the
domain's SPF, DKIM and DMARC records at its DNS provider, otherwise Gmail rejects or
spam-folders the reminders (check with a test message: *Show original* lists
`spf=pass`, `dkim=pass`, `dmarc=pass`).

Secret values never go through Terraform, so they stay out of the state:

```sh
openssl rand -base64 48 | tr -d '\n' | gcloud secrets versions add session-secret --data-file=- --project=<project-id>
GCLOUD_CONFIGURATION=<config> scripts/upload_household.sh <project-id>
read -rs P && printf '%s' "$P" | gcloud secrets versions add smtp-password --data-file=- --project=<project-id>; unset P
```

The `web` service and the `jobs` job run the image deployed by `scripts/deploy.sh`;
Terraform ignores image changes. Cloud Scheduler starts `jobs` at 07:00 Europe/Warsaw.
Cloud Run reserves `/healthz`, so the health check is `/health`.

## Running locally

`infra/tf` passes an access token from an explicit gcloud configuration, so
Application Default Credentials of another account are never used:

```sh
GCLOUD_CONFIGURATION=<config> infra/tf init -backend-config=backend.hcl
GCLOUD_CONFIGURATION=<config> infra/tf plan
```

## CI

`.github/workflows/terraform.yml` runs plan and apply on pushes to `main` in the
`production` environment. Repository variables (from `terraform output`):

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID` | project id |
| `GCP_WIF_PROVIDER` | `wif_provider` |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `deploy_service_account` |
| `GCP_EVAL_SERVICE_ACCOUNT` | `eval_service_account` |
| `GOOGLE_CLIENT_ID` | OAuth client id |

The repository is public and so are its Actions logs. Values that should not be
published are repository secrets instead, which GitHub masks in logs:

| Secret | Value |
|---|---|
| `GCP_BILLING_ACCOUNT_ID` | billing account id |
| `WEB_BASE_URL` | service URL |
| `SMTP_HOST` | reminder mailbox SMTP server |
| `SMTP_USER` | reminder mailbox address |

Create GitHub environments `production` (deployment branch: `main` only) and `eval`.
