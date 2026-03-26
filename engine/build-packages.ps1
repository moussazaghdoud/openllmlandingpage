param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutDir = Join-Path $Root "dist"
$SecureLLMSource = "C:\Users\zaghdoud\securellm"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Building SecureLLM Packages v$Version" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Validate securellm source exists
if (-not (Test-Path (Join-Path $SecureLLMSource "app"))) {
    Write-Host "[ERROR] SecureLLM source not found at $SecureLLMSource\app" -ForegroundColor Red
    Write-Host "        Clone the securellm repo to $SecureLLMSource first." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $SecureLLMSource "requirements.txt"))) {
    Write-Host "[ERROR] requirements.txt not found at $SecureLLMSource" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Using securellm source from: $SecureLLMSource" -ForegroundColor Blue

# Clean
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Path $OutDir | Out-Null

# ===========================================
# LINUX PACKAGE
# ===========================================
Write-Host "[1/2] Building Linux package..." -ForegroundColor Blue

$linuxDir = Join-Path $OutDir "securellm-engine-$Version-linux"
$linuxEngine = Join-Path $linuxDir "engine"

New-Item -ItemType Directory -Force -Path $linuxEngine | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $linuxDir "nginx") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $linuxDir "config") | Out-Null

# Engine source -- copied from the REAL securellm repo
Copy-Item -Recurse -Force (Join-Path $SecureLLMSource "app") $linuxEngine
Get-ChildItem -Path $linuxEngine -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item -Force (Join-Path $SecureLLMSource "requirements.txt") $linuxEngine
Copy-Item -Force (Join-Path $Root "Dockerfile") $linuxEngine

# NATS Bridge
$linuxBridge = Join-Path $linuxDir "bridge"
New-Item -ItemType Directory -Force -Path $linuxBridge | Out-Null
Copy-Item -Force (Join-Path $Root "bridge\bridge.py") $linuxBridge
Copy-Item -Force (Join-Path $Root "bridge\requirements.txt") $linuxBridge
Copy-Item -Force (Join-Path $Root "bridge\Dockerfile") $linuxBridge

# NATS Leaf Node
$linuxNats = Join-Path $linuxDir "nats"
New-Item -ItemType Directory -Force -Path $linuxNats | Out-Null
Copy-Item -Force (Join-Path $Root "nats\nats-leaf.conf") $linuxNats
Copy-Item -Force (Join-Path $Root "nats\docker-entrypoint.sh") $linuxNats
Copy-Item -Force (Join-Path $Root "nats\Dockerfile") $linuxNats

# Deploy files
Copy-Item -Force (Join-Path $Root "deploy\docker-compose.prod.yml") $linuxDir
Copy-Item -Force (Join-Path $Root "deploy\install.sh") $linuxDir
Copy-Item -Force (Join-Path $Root "deploy\securellm.sh") $linuxDir
Copy-Item -Recurse -Force (Join-Path $Root "deploy\nginx\*") (Join-Path $linuxDir "nginx")
Copy-Item -Recurse -Force (Join-Path $Root "deploy\config\*") (Join-Path $linuxDir "config")
Copy-Item -Force (Join-Path $Root "deploy\README-DEPLOY.md") (Join-Path $linuxDir "README.md")

# .env.example
Copy-Item -Force (Join-Path $Root ".env.example") (Join-Path $linuxDir "config\.env.example")

# Version file
@"
SecureLLM Privacy Gateway
Version: $Version
Platform: Linux
Built: $(Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
"@ | Set-Content (Join-Path $linuxDir "VERSION")

# Quickstart
@"
=============================================
  SecureLLM Privacy Gateway - Quick Start
  Linux Edition
=============================================

STEP 1: Ensure Docker and Docker Compose are installed.

STEP 2: Run the installer:

    chmod +x install.sh
    sudo ./install.sh

STEP 3: Save the Admin API key displayed at the end.

STEP 4: Test:

    curl -sk https://localhost/health

STEP 5: Test anonymization:

    curl -sk https://localhost/v1/anonymize \
      -H "Authorization: Bearer YOUR_ADMIN_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{"text": "John Smith from Acme Corp"}'

Done. Full documentation is in README.md.
=============================================
"@ | Set-Content (Join-Path $linuxDir "QUICKSTART.txt")

# Create tar.gz
$linuxTar = Join-Path $OutDir "securellm-engine-$Version-linux.tar.gz"
$linuxZipFallback = Join-Path $OutDir "securellm-engine-$Version-linux.zip"
try {
    Push-Location $OutDir
    & "$env:SystemRoot\System32\tar.exe" -czf $linuxTar "securellm-engine-$Version-linux" 2>$null
    Pop-Location
    $linuxOut = $linuxTar
} catch {
    Pop-Location
    Compress-Archive -Path $linuxDir -DestinationPath $linuxZipFallback -Force
    $linuxOut = $linuxZipFallback
}

$linuxSize = (Get-Item $linuxOut).Length / 1KB
Write-Host "  Created: $linuxOut ($([math]::Round($linuxSize, 1)) KB)" -ForegroundColor Green

# ===========================================
# WINDOWS PACKAGE
# ===========================================
Write-Host "[2/2] Building Windows package..." -ForegroundColor Blue

$winDir = Join-Path $OutDir "securellm-engine-$Version-windows"
$winEngine = Join-Path $winDir "engine"

New-Item -ItemType Directory -Force -Path $winEngine | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $winDir "nginx") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $winDir "config") | Out-Null

# Engine source -- copied from the REAL securellm repo
Copy-Item -Recurse -Force (Join-Path $SecureLLMSource "app") $winEngine
Get-ChildItem -Path $winEngine -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item -Force (Join-Path $SecureLLMSource "requirements.txt") $winEngine
Copy-Item -Force (Join-Path $Root "Dockerfile") $winEngine

# NATS Bridge
$winBridge = Join-Path $winDir "bridge"
New-Item -ItemType Directory -Force -Path $winBridge | Out-Null
Copy-Item -Force (Join-Path $Root "bridge\bridge.py") $winBridge
Copy-Item -Force (Join-Path $Root "bridge\requirements.txt") $winBridge
Copy-Item -Force (Join-Path $Root "bridge\Dockerfile") $winBridge

# NATS Leaf Node
$winNats = Join-Path $winDir "nats"
New-Item -ItemType Directory -Force -Path $winNats | Out-Null
Copy-Item -Force (Join-Path $Root "nats\nats-leaf.conf") $winNats
Copy-Item -Force (Join-Path $Root "nats\docker-entrypoint.sh") $winNats
Copy-Item -Force (Join-Path $Root "nats\Dockerfile") $winNats

# Deploy files (Windows versions)
Copy-Item -Force (Join-Path $Root "deploy\docker-compose.prod.yml") $winDir
Copy-Item -Force (Join-Path $Root "deploy-windows\install.ps1") $winDir
Copy-Item -Force (Join-Path $Root "deploy-windows\securellm.ps1") $winDir
Copy-Item -Recurse -Force (Join-Path $Root "deploy\nginx\*") (Join-Path $winDir "nginx")
Copy-Item -Recurse -Force (Join-Path $Root "deploy\config\*") (Join-Path $winDir "config")
Copy-Item -Force (Join-Path $Root "deploy\README-DEPLOY.md") (Join-Path $winDir "README.md")
Copy-Item -Force (Join-Path $Root "deploy-windows\QUICKSTART.txt") $winDir

# .env.example
Copy-Item -Force (Join-Path $Root ".env.example") (Join-Path $winDir "config\.env.example")

# Version file
@"
SecureLLM Privacy Gateway
Version: $Version
Platform: Windows
Built: $(Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
"@ | Set-Content (Join-Path $winDir "VERSION")

# Create zip
$winZip = Join-Path $OutDir "securellm-engine-$Version-windows.zip"
Compress-Archive -Path $winDir -DestinationPath $winZip -Force

$winSize = (Get-Item $winZip).Length / 1KB
Write-Host "  Created: $winZip ($([math]::Round($winSize, 1)) KB)" -ForegroundColor Green

# ===========================================
# SUMMARY
# ===========================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Packages Built Successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Linux:   dist\securellm-engine-$Version-linux.tar.gz"
Write-Host "  Windows: dist\securellm-engine-$Version-windows.zip"
Write-Host ""
Write-Host "  Source:  $SecureLLMSource\app\ (real securellm backend)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Deliver the appropriate file to the customer." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Customer installs with:" -ForegroundColor White
Write-Host "    Linux:   tar xzf ... && sudo ./install.sh" -ForegroundColor Gray
Write-Host "    Windows: Expand-Archive ... && .\install.ps1" -ForegroundColor Gray
Write-Host ""
