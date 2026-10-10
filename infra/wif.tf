# GitHub Actions -> GCP without keys. Two identities, each bound to one GitHub
# environment of this repository (OIDC subject repo:<owner>/<name>:environment:<env>):
#   production -> deploy (Terraform + deploy, only from main via environment protection)
#   eval       -> eval (model calls only, no data or infrastructure access)

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.this]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions OIDC"

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner_id"
    "attribute.environment"      = "assertion.environment"
    "attribute.ref"              = "assertion.ref"
  }

  attribute_condition = "assertion.repository_owner_id == '${var.github_owner_id}' && assertion.repository == '${var.github_repository}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

locals {
  wif_subject_prefix = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/subject/repo:${var.github_repository}:environment"
}

resource "google_service_account" "deploy" {
  account_id   = "gh-deploy"
  display_name = "GitHub Actions: Terraform and deploy (environment production)"

  depends_on = [google_project_service.this]
}

resource "google_service_account" "eval" {
  account_id   = "gh-eval"
  display_name = "GitHub Actions: evaluation (environment eval)"

  depends_on = [google_project_service.this]
}

resource "google_service_account_iam_member" "deploy_wif" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_subject_prefix}:production"
}

resource "google_service_account_iam_member" "eval_wif" {
  service_account_id = google_service_account.eval.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_subject_prefix}:eval"
}

# Terraform manages IAM, service accounts and APIs in this single-purpose project,
# so the deploy identity is project owner. It is reachable only from the protected
# `production` environment.
resource "google_project_iam_member" "deploy_owner" {
  project = var.project_id
  role    = "roles/owner"
  member  = google_service_account.deploy.member
}

# Lets Terraform in CI read and update the budget.
resource "google_billing_account_iam_member" "deploy_budget" {
  billing_account_id = var.billing_account_id
  role               = "roles/billing.costsManager"
  member             = google_service_account.deploy.member

  depends_on = [google_project_service.this]
}

resource "google_project_iam_member" "eval" {
  for_each = toset(["roles/aiplatform.user", "roles/dlp.user"])

  project = var.project_id
  role    = each.value
  member  = google_service_account.eval.member
}
