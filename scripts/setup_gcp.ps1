# One-time Google Cloud setup. Usage:  .\scripts\setup_gcp.ps1 -Project your-project-id
param([Parameter(Mandatory = $true)][string]$Project, [string]$Region = "asia-south1")
$ErrorActionPreference = "Stop"

gcloud config set project $Project
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
  aiplatform.googleapis.com bigquery.googleapis.com firestore.googleapis.com

# Firestore (decisions + audit trail). Ignore the error if it already exists.
gcloud firestore databases create --location=$Region 2>$null

# BigQuery dataset + evidence tables
bq --location=$Region mk --dataset "${Project}:arqon" 2>$null
bq load --replace --source_format=NEWLINE_DELIMITED_JSON "${Project}:arqon.events" data/bq/events.jsonl data/bq/events_schema.json
bq load --replace --source_format=NEWLINE_DELIMITED_JSON "${Project}:arqon.cases" data/bq/cases.jsonl data/bq/cases_schema.json

# Let Cloud Run's service account call Gemini (Vertex AI), BigQuery and Firestore
$num = gcloud projects describe $Project --format="value(projectNumber)"
$sa = "$num-compute@developer.gserviceaccount.com"
foreach ($role in @("roles/aiplatform.user", "roles/bigquery.dataViewer", "roles/bigquery.jobUser", "roles/datastore.user")) {
  gcloud projects add-iam-policy-binding $Project --member="serviceAccount:$sa" --role=$role --condition=None | Out-Null
}
Write-Host "GCP setup done for $Project"
