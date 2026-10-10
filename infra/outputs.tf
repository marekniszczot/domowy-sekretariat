output "web_url" {
  value = google_cloud_run_v2_service.web.uri
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "ocr_processor" {
  value = google_document_ai_processor.ocr.id
}

output "tasks_queue" {
  value = google_cloud_tasks_queue.process.id
}

# Values for GitHub repository variables used by the workflows.
output "wif_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "deploy_service_account" {
  value = google_service_account.deploy.email
}

output "eval_service_account" {
  value = google_service_account.eval.email
}
