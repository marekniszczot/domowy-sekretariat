# Runtime identities

resource "google_service_account" "web" {
  account_id   = "web-runtime"
  display_name = "Cloud Run web"

  depends_on = [google_project_service.this]
}

resource "google_service_account" "jobs" {
  account_id   = "jobs-runtime"
  display_name = "Cloud Run job"

  depends_on = [google_project_service.this]
}

resource "google_service_account" "tasks" {
  account_id   = "tasks-invoker"
  display_name = "Cloud Tasks OIDC identity for /internal/process"

  depends_on = [google_project_service.this]
}

resource "google_service_account" "scheduler" {
  account_id   = "scheduler-invoker"
  display_name = "Cloud Scheduler trigger for the daily job"

  depends_on = [google_project_service.this]
}

locals {
  web_roles = [
    "roles/aiplatform.user",
    "roles/cloudtasks.enqueuer",
    "roles/datastore.user",
    "roles/dlp.user",
    "roles/documentai.apiUser",
  ]
  jobs_roles = [
    "roles/datastore.user",
  ]
}

resource "google_project_iam_member" "web" {
  for_each = toset(local.web_roles)

  project = var.project_id
  role    = each.value
  member  = google_service_account.web.member
}

resource "google_project_iam_member" "jobs" {
  for_each = toset(local.jobs_roles)

  project = var.project_id
  role    = each.value
  member  = google_service_account.jobs.member
}

resource "google_storage_bucket_iam_member" "letters" {
  for_each = {
    web  = google_service_account.web.member
    jobs = google_service_account.jobs.member
  }

  bucket = google_storage_bucket.letters.name
  role   = "roles/storage.objectAdmin"
  member = each.value
}

resource "google_secret_manager_secret_iam_member" "web" {
  for_each = google_secret_manager_secret.this

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.web.member
}

resource "google_secret_manager_secret_iam_member" "jobs" {
  for_each = { for name, secret in google_secret_manager_secret.this : name => secret if name != "session-secret" }

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.jobs.member
}

# web creates tasks that carry an OIDC token of the tasks identity.
resource "google_service_account_iam_member" "web_acts_as_tasks" {
  service_account_id = google_service_account.tasks.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.web.member
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_runs_jobs" {
  name     = google_cloud_run_v2_job.jobs.name
  location = var.region
  role     = "roles/run.invoker"
  member   = google_service_account.scheduler.member
}
