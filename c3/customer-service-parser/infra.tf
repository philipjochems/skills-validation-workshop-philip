# ==============================================================================
# PROVIDER CONFIGURATION & APIS
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required GCP APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "bigquery.googleapis.com",
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# ==============================================================================
# BIGQUERY INFRASTRUCTURE
# ==============================================================================

# BigQuery Dataset
resource "google_bigquery_dataset" "support_ops" {
  dataset_id                 = var.dataset_id
  friendly_name              = "Support Operations"
  description                = "Dataset storing extracted support transcript records and AI analysis"
  location                   = var.location
  delete_contents_on_destroy = false

  depends_on = [google_project_service.required_apis]
}

# BigQuery Table
resource "google_bigquery_table" "transcript_records" {
  dataset_id          = google_bigquery_dataset.support_ops.dataset_id
  table_id            = var.table_id
  deletion_protection = false

  schema = jsonencode([
    {
      name        = "call_id"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Unique identified extracted from transcript"
    },
    {
      name        = "parsed_json"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Full structured JSON object extracted by Gemini"
    },
    {
      name        = "original_transcript"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Raw text input transcript"
    },
    {
      name        = "processed_at"
      type        = "TIMESTAMP"
      mode        = "NULLABLE"
      description = "UTC ISO timestamp when record was written"
    },
    {
      name        = "status"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Processing status indicator (e.g. SUCCESS)"
    }
  ])
}

# ==============================================================================
# IAM & SERVICE ACCOUNT FOR PARSER RUNNER
# ==============================================================================

# Service account for executing the transcript parser script
resource "google_service_account" "transcript_runner" {
  account_id   = "transcript-parser-sa"
  display_name = "Transcript Parser Script Service Account"
  description  = "Used by local/CI runners to invoke Vertex AI Gemini and write into BigQuery"
}

# BigQuery Data Editor permissions
resource "google_project_iam_member" "bq_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.transcript_runner.email}"
}

# BigQuery Job User permissions (required to stream/insert data)
resource "google_project_iam_member" "bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.transcript_runner.email}"
}

# Vertex AI User permissions for Gemini invocation
resource "google_project_iam_member" "vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.transcript_runner.email}"
}

# ==============================================================================
# ARTIFACT REGISTRY & CLOUD RUN DEPLOYMENT
# ==============================================================================

resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "transcript-parser"
  description   = "Docker repository for the customer service transcript parser app"
  format        = "DOCKER"

  depends_on = [google_project_service.required_apis]
}

# Automatically build and push the Docker image during terraform apply
resource "terraform_data" "docker_build_push" {
  triggers_replace = [
    md5(file("${path.module}/Dockerfile")),
    md5(file("${path.module}/app.py")),
    md5(file("${path.module}/parse_transcript.py"))
  ]

  provisioner "local-exec" {
    command = <<EOT
      gcloud auth configure-docker ${var.region}-docker.pkg.dev --quiet
      docker build --platform linux/amd64 -t ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/app:latest ${path.module}
      docker push ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/app:latest
    EOT
  }

  depends_on = [google_artifact_registry_repository.repo]
}

resource "google_cloud_run_v2_service" "app" {
  name     = "transcript-parser-ui"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.transcript_runner.email

    scaling {
      max_instance_count = 5
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/transcript-parser/app:latest"

      env {
        name  = "BQ_DATASET"
        value = var.dataset_id
      }
      env {
        name  = "BQ_TABLE"
        value = var.table_id
      }
    }
  }

  depends_on = [
    google_project_service.required_apis,
    terraform_data.docker_build_push
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ==============================================================================
# VARIABLES
# ==============================================================================

variable "project_id" {
  type        = string
  description = "The GCP Project ID where resources will be deployed."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Default GCP Region."
}

variable "location" {
  type        = string
  default     = "US"
  description = "GCP location for BigQuery multi-region dataset (must match script setting)."
}

variable "dataset_id" {
  type        = string
  default     = "support_ops"
  description = "BigQuery dataset ID matching BQ_DATASET env variable."
}

variable "table_id" {
  type        = string
  default     = "transcript_records"
  description = "BigQuery table ID matching BQ_TABLE env variable."
}

# ==============================================================================
# OUTPUTS
# ==============================================================================

output "bigquery_dataset_id" {
  value       = google_bigquery_dataset.support_ops.dataset_id
  description = "Target BigQuery Dataset ID"
}

output "bigquery_table_id" {
  value       = google_bigquery_table.transcript_records.table_id
  description = "Target BigQuery Table ID"
}

output "service_account_email" {
  value       = google_service_account.transcript_runner.email
  description = "Email of created Service Account to configure credentials for the execution context"
}

output "cloud_run_url" {
  value       = google_cloud_run_v2_service.app.uri
  description = "The URL of the deployed Streamlit application on Cloud Run"
}