# Deploy ARQON to Cloud Run. Usage:  .\scripts\deploy.ps1 -Project your-project-id [-Model gemini-2.5-flash]
param([Parameter(Mandatory = $true)][string]$Project, [string]$Region = "asia-south1", [string]$Model = "gemini-2.5-flash")
$ErrorActionPreference = "Stop"

$vars = "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$Project,GOOGLE_CLOUD_LOCATION=us-central1," +
        "GEMINI_MODEL=$Model,ARQON_BQ_DATASET=$Project.arqon,ARQON_FIRESTORE=1"

gcloud run deploy arqon --source . --project $Project --region $Region `
  --allow-unauthenticated --min-instances 1 --memory 1Gi --timeout 120 `
  --set-env-vars $vars

gcloud run services describe arqon --project $Project --region $Region --format="value(status.url)"
