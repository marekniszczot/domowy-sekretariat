terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.6"
    }
  }

  # Bucket name comes from backend.hcl (created by bootstrap.sh).
  backend "gcs" {
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region

  # Needed for APIs that require a quota project with user credentials (e.g. billing budgets).
  user_project_override = true
  billing_project       = var.project_id
}

data "google_project" "this" {}
