resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "app"
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "2592000s"
    }
  }

  depends_on = [google_project_service.this]
}

# API + PWA. Public, because the PWA is opened from phones; every API call verifies
# a Firebase ID token in the app, and /internal/* verifies the Cloud Tasks OIDC token.
resource "google_cloud_run_v2_service" "web" {
  name                = "web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.web.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.placeholder_image
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.this]
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  name     = google_cloud_run_v2_service.web.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Daily job: reminders and retention.
resource "google_cloud_run_v2_job" "jobs" {
  name                = "jobs"
  location            = var.region
  deletion_protection = false

  template {
    task_count = 1

    template {
      service_account = google_service_account.jobs.email
      max_retries     = 1

      containers {
        image = var.placeholder_image
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.this]
}

resource "google_cloud_tasks_queue" "process" {
  name     = "process-letters"
  location = var.region

  retry_config {
    max_attempts  = 5
    min_backoff   = "10s"
    max_backoff   = "300s"
    max_doublings = 4
  }

  rate_limits {
    max_concurrent_dispatches = 2
  }

  depends_on = [google_project_service.this]
}

# Paused until the reminders job exists (T8).
resource "google_cloud_scheduler_job" "daily" {
  name      = "daily-jobs"
  region    = var.region
  schedule  = "0 7 * * *"
  time_zone = "Europe/Warsaw"
  paused    = true

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/${google_cloud_run_v2_job.jobs.id}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.this]
}
