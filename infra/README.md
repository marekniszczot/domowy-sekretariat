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
| `GCP_BILLING_ACCOUNT_ID` | billing account id |
| `GCP_WIF_PROVIDER` | `wif_provider` |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `deploy_service_account` |

Create GitHub environments `production` (deployment branch: `main` only) and `eval`.
