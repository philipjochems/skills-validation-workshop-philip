provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Enable Required Google Cloud APIs
resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "modelarmor.googleapis.com",
    "logging.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com"
  ])
  service            = each.value
  disable_on_destroy = false
}

# 2. Dedicated Service Account for the Application
resource "google_service_account" "ads_app_sa" {
  account_id   = "ads-document-synthesis-sa"
  display_name = "ADS Document Synthesis Service Account"
}

# 3. Assign IAM Roles (Least Privilege)
resource "google_project_iam_member" "app_roles" {
  for_each = toset([
    "roles/aiplatform.user",      # For Gemini calls
    "roles/modelarmor.user",      # For sanitization
    "roles/bigquery.dataEditor",  # For writing to BQ
    "roles/logging.logWriter",     # For audit logs
    "roles/artifactregistry.reader" # For reading artifact registry packages safely
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.ads_app_sa.email}"
}

# 4. BigQuery Dataset and Table (matches parse_document.py schema)
resource "google_bigquery_dataset" "support_ops" {
  dataset_id = "support_ops"
  location   = "US"
  depends_on = [google_project_service.services]
}

resource "google_bigquery_table" "document_records" {
  dataset_id = google_bigquery_dataset.support_ops.dataset_id
  table_id   = "document_records"
  deletion_protection = false

  schema = <<EOF
[
  {"name": "call_id", "type": "STRING", "mode": "NULLABLE"},
  {"name": "parsed_json", "type": "STRING", "mode": "NULLABLE"},
  {"name": "original_document", "type": "STRING", "mode": "NULLABLE"},
  {"name": "processed_at", "type": "TIMESTAMP", "mode": "NULLABLE"},
  {"name": "status", "type": "STRING", "mode": "NULLABLE"}
]
EOF
}

# 5. Artifact Registry for Docker Images
resource "google_artifact_registry_repository" "ads_repo" {
  location      = var.region
  repository_id = "ads-deployments"
  format        = "DOCKER"
  depends_on    = [google_project_service.services]
}

# 5.1 Build and Push Docker Image using Cloud Build
resource "terraform_data" "app_build" {
  triggers_replace = [
    sha256(file("${path.module}/app.py")),
    sha256(file("${path.module}/parse_document.py"))
  ]

  provisioner "local-exec" {
    command = "gcloud builds submit --tag ${google_artifact_registry_repository.ads_repo.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ads_repo.repository_id}/ads-app:latest ."
  }

  depends_on = [google_project_service.services, google_artifact_registry_repository.ads_repo]
}

# 6. Cloud Run Service
resource "google_cloud_run_v2_service" "ads_app" {
  name     = "ads-doc-synthesis"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.ads_app_sa.email
    containers {
      image = "${google_artifact_registry_repository.ads_repo.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ads_repo.repository_id}/ads-app:latest"
      ports {
        container_port = 8080
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET"
        value = google_bigquery_dataset.support_ops.dataset_id
      }
      env {
        name  = "BQ_TABLE"
        value = google_bigquery_table.document_records.table_id
      }
      env {
        name  = "APP_VERSION"
        value = sha256(join("", [file("${path.module}/app.py"), file("${path.module}/parse_document.py")]))
      }
    }
  }

  depends_on = [
    google_project_service.services,
    google_project_iam_member.app_roles,
    terraform_data.app_build
  ]
}

# 7. Allow Public Access (Optional, depends on Department policy)
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  location = google_cloud_run_v2_service.ads_app.location
  project  = var.project_id
  name     = google_cloud_run_v2_service.ads_app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "app_url" {
  value = google_cloud_run_v2_service.ads_app.uri
}

output "registry_image_path" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ads_repo.repository_id}/ads-app:latest"
}