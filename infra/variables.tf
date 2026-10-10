variable "project_id" {
  type = string
}

variable "region" {
  description = "Region for data and services. Document AI uses the `eu` multi-region."
  type        = string
  default     = "europe-central2"
}

variable "billing_account_id" {
  description = "Billing account the budget is attached to."
  type        = string
}

variable "budget_amount" {
  description = "Monthly budget in the billing account currency. Alerts at 20%, 50% and 100%."
  type        = number
  default     = 200
}

variable "budget_currency" {
  description = "Must match the billing account currency."
  type        = string
  default     = "PLN"
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to use Workload Identity Federation."
  type        = string
}

variable "github_owner_id" {
  description = "Numeric GitHub id of the repository owner (protects against a recreated owner name)."
  type        = string
}

variable "placeholder_image" {
  description = "Image used until the first real deploy. Terraform ignores later image changes."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "google_client_id" {
  description = "OAuth client id for Sign in with Google (created by hand, see README)."
  type        = string
}

variable "web_base_url" {
  description = "Public URL of the web service, registered in the OAuth client."
  type        = string
}
