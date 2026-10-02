param(
    [Parameter(Mandatory=$true)][string]$EnvFile,
    [Parameter(Mandatory=$true)][string]$SecretVersionsFile,
    [string]$Project = 'duck-inventory',
    [string]$Region = 'asia-southeast1',
    [string]$Service = 'duck-inventory',
    [string]$Gcloud = 'gcloud',
    [switch]$Private
)
$ErrorActionPreference = 'Stop'
# Run only after the monthly Cloud Run spend cap is verified in Billing.
# EnvFile contains non-secret runtime settings. SecretVersionsFile maps env names
# to Secret Manager name:NUMERIC_VERSION references, never secret values.
$source = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$settings = Get-Content -LiteralPath $EnvFile -Raw | ConvertFrom-Json
$refs = Get-Content -LiteralPath $SecretVersionsFile -Raw | ConvertFrom-Json
$required = @('DATABASE_URL','SECRET_KEY','GOOGLE_CLIENT_SECRET','SUPABASE_SERVICE_KEY')
$secretArgs = @()
foreach ($key in $required) {
    $reference = $refs.$key
    if ($reference -notmatch '^[a-zA-Z0-9_-]+:[1-9][0-9]*$') { throw "Missing or invalid pinned secret reference: $key" }
    if ($settings.PSObject.Properties.Name -contains $key) { throw "Secret $key must not be placed in EnvFile" }
    $secretArgs += "$key=$reference"
}
if ($settings.CLOUD_MODE -ne 'true' -or $settings.STORAGE_BACKEND -ne 'supabase' -or $settings.AUTH_MODE -ne 'google') {
    throw 'Environment must specify cloud mode, Supabase storage and Google authentication'
}
$serviceAccount = "duck-runtime@$Project.iam.gserviceaccount.com"
$accessFlag = if ($Private) { '--no-allow-unauthenticated' } else { '--allow-unauthenticated' }
& $Gcloud run deploy $Service "--project=$Project" "--region=$Region" "--source=$source" `
    "--build-service-account=projects/$Project/serviceAccounts/duck-build@$Project.iam.gserviceaccount.com" `
    "--service-account=$serviceAccount" "--env-vars-file=$EnvFile" "--set-secrets=$($secretArgs -join ',')" `
    $accessFlag --min=0 --max=1 --min-instances=0 --max-instances=1 `
    --cpu=1 --memory=512Mi --concurrency=4 --timeout=60 --port=8080 `
    --cpu-throttling --no-cpu-boost `
    '--startup-probe=httpGet.path=/health,httpGet.port=8080,timeoutSeconds=10,periodSeconds=15,failureThreshold=4' `
    --quiet
if ($LASTEXITCODE -ne 0) { throw 'Cloud Run deployment failed; existing revision was not intentionally removed' }
