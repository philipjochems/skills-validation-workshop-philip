terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID"
}

variable "region" {
  type        = string
  description = "The target region for deployment"
  default     = "us-central1"
}

# Enable necessary Google Cloud APIs
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com"
  ])
  service            = each.key
  disable_on_destroy = false
}

# Create an Artifact Registry repository to hold the application image
resource "google_artifact_registry_repository" "repo" {
  depends_on    = [google_project_service.services]
  location      = var.region
  repository_id = "chatbot-repo"
  description   = "Docker repository for Streamlit AI Chatbot"
  format        = "DOCKER"
}

# Create a secure IAM Service Account for the Cloud Run instance
resource "google_service_account" "chatbot_sa" {
  account_id   = "chatbot-runner"
  display_name = "Cloud Run Chatbot Service Account"
}

# Assign Vertex AI User permissions to the Service Account
resource "google_project_iam_member" "vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.chatbot_sa.email}"
}

# Automate the Docker build and push to Artifact Registry using Cloud Build
resource "terraform_data" "docker_build" {
  depends_on = [google_artifact_registry_repository.repo]

  # Trigger a rebuild whenever app.py or the Dockerfile changes
  triggers_replace = [
    filemd5("${path.module}/app.py"),
    filemd5("${path.module}/Dockerfile")
  ]

  provisioner "local-exec" {
    command     = "gcloud builds submit --project=${var.project_id} --tag ${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/app:latest ${path.module}"
    working_dir = path.module
  }
}

# Deploy the service to Cloud Run
resource "google_cloud_run_v2_service" "chatbot_service" {
  name     = "ai-chatbot"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.chatbot_sa.email
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/app:latest"
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
      }
    }
  }
  depends_on = [
    google_project_iam_member.vertex_ai_user,
    terraform_data.docker_build
  ]
}

# Grant public unauthenticated access to the web UI
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  name     = google_cloud_run_v2_service.chatbot_service.name
  location = google_cloud_run_v2_service.chatbot_service.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "service_url" {
  value       = google_cloud_run_v2_service.chatbot_service.uri
  description = "The public URL of your deployed Streamlit chatbot"
}