# Uploaded letters (photos/PDFs). Deleted after 30 days; soft delete is off so the
# 30-day retention promised in the privacy notes is real.
resource "google_storage_bucket" "letters" {
  name     = "${var.project_id}-letters"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.this]
}

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  deletion_policy         = "DELETE"

  depends_on = [google_project_service.this]
}

resource "google_document_ai_processor" "ocr" {
  location     = "eu"
  display_name = "ocr"
  type         = "OCR_PROCESSOR"

  depends_on = [google_project_service.this]
}

# Containers only; versions are added outside this task (household config: T10, SMTP: T8).
resource "google_secret_manager_secret" "this" {
  for_each = toset(["household-config", "smtp-password"])

  secret_id = each.value

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.this]
}
