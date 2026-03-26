#Requires -RunAsAdministrator
param(
    [string]$InstallDir = "C:\SecureLLM",
    [string]$Port = "443",
    [string]$TlsCertPath = "",
    [string]$TlsKeyPath = ""
)

$ErrorActionPreference = "Stop"

function Write-Header {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  SecureLLM Privacy Gateway" -ForegroundColor Cyan
    Write-Host "  Enterprise On-Premise Installer" -ForegroundColor Cyan
    Write-Host "  Windows Edition" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Info  { param($Msg) Write-Host "[INFO] " -ForegroundColor Blue -NoNewline; Write-Host $Msg }
function Write-Ok    { param($Msg) Write-Host "[OK]   " -ForegroundColor Green -NoNewline; Write-Host $Msg }
function Write-Warn  { param($Msg) Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline; Write-Host $Msg }
function Write-Err   { param($Msg) Write-Host "[ERROR]" -ForegroundColor Red -NoNewline; Write-Host $Msg }

function Test-Prerequisites {
    Write-Info "Checking prerequisites..."

    $missing = $false

    try {
        $dockerVer = docker --version 2>$null
        Write-Ok "Docker: $dockerVer"
    } catch {
        Write-Err "Docker is not installed. Install Docker Desktop for Windows first."
        $missing = $true
    }

    try {
        docker compose version 2>$null | Out-Null
        Write-Ok "Docker Compose available"
    } catch {
        Write-Err "Docker Compose not available."
        $missing = $true
    }

    if ($missing) {
        Write-Err "Missing prerequisites. Aborting."
        exit 1
    }
    Write-Host ""
}

function New-RandomHex {
    param([int]$Length = 32)
    $bytes = New-Object byte[] ($Length / 2)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ($bytes | ForEach-Object { $_.ToString("x2") }) -join ''
}

function Initialize-Directories {
    Write-Info "Setting up directories at $InstallDir..."

    $dirs = @("config", "data\redis", "certs", "logs", "backups", "engine")
    foreach ($d in $dirs) {
        New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir $d) | Out-Null
    }

    Write-Ok "Directory structure created"
}

function Initialize-Config {
    $envFile = Join-Path $InstallDir "config\.env"

    if ((Test-Path $envFile) -and (-not $env:FORCE_RECONFIGURE)) {
        Write-Warn "Configuration already exists. Set `$env:FORCE_RECONFIGURE=1 to overwrite."
        return @{}
    }

    Write-Info "Configuring SecureLLM..."

    $apiSecretKey = New-RandomHex -Length 64
    $redisPassword = New-RandomHex -Length 32
    $instanceId = "$($env:COMPUTERNAME)-$(New-RandomHex -Length 8)"
    $localNatsToken = New-RandomHex -Length 32

    # Admin API Key
    $adminApiKey = if ($env:ADMIN_API_KEY) { $env:ADMIN_API_KEY } else { Read-Host "Enter an Admin API key (or press Enter to auto-generate)" }
    if (-not $adminApiKey) {
        $adminApiKey = New-RandomHex -Length 40
    }

    # License Key
    $licenseKey = if ($env:SECURELLM_LICENSE_KEY) { $env:SECURELLM_LICENSE_KEY } else { Read-Host "Enter your SecureLLM license key (provided by your vendor)" }

    # Workspace ID
    $workspaceId = if ($env:WORKSPACE_ID) { $env:WORKSPACE_ID } else { Read-Host "Enter your Workspace ID (assigned by the admin on Railway)" }

    $envContent = @"
# SecureLLM On-Premise Configuration
# Generated on $(Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
# DO NOT share this file - it contains secrets.

# === Redis ===
REDIS_URL=redis://:$redisPassword@redis:6379/0
REDIS_PASSWORD=$redisPassword

# === Auth ===
API_SECRET_KEY=$apiSecretKey
ADMIN_API_KEY=$adminApiKey

# === Presidio ===
PRESIDIO_EXTERNAL_URL=

# === Server ===
HOST=0.0.0.0
PORT=8000

# === On-Premise Settings ===
DEPLOYMENT_MODE=onprem
LICENSE_KEY=$licenseKey
SAAS_URL=https://securellm.railway.app
INSTANCE_ID=$instanceId

# === NATS Tunnel ===
LOCAL_NATS_TOKEN=$localNatsToken
SAAS_NATS_URL=wss://securellm.railway.app:443/nats
WORKSPACE_ID=$workspaceId
NATS_CREDENTIALS=
ENGINE_URL=http://engine:8000
NATS_URL=nats://nats-leaf:4222
HEARTBEAT_INTERVAL=30
ENGINE_VERSION=1.0.0

# === Networking (for Docker Compose) ===
HTTPS_PORT=$Port
"@

    Set-Content -Path $envFile -Value $envContent -Encoding UTF8

    Write-Ok "Configuration written"
    Write-Host ""
    Write-Host "  Admin API Key:     $adminApiKey" -ForegroundColor White
    Write-Host "  Instance ID:       $instanceId" -ForegroundColor White
    Write-Host "  Workspace ID:      $workspaceId" -ForegroundColor White
    Write-Host "  HTTPS Port:        $Port" -ForegroundColor White
    Write-Host ""
    Write-Host "  Save these credentials securely. They won't be shown again." -ForegroundColor Yellow
    Write-Host ""

    return @{ AdminApiKey = $adminApiKey }
}

function Initialize-TLS {
    $certDir = Join-Path $InstallDir "certs"
    $certFile = Join-Path $certDir "server.crt"
    $keyFile = Join-Path $certDir "server.key"

    if ((Test-Path $certFile) -and (-not $env:FORCE_RECONFIGURE)) {
        Write-Ok "TLS certificates already exist"
        return
    }

    if ($TlsCertPath -and $TlsKeyPath) {
        Write-Info "Using provided TLS certificates..."
        Copy-Item $TlsCertPath $certFile
        Copy-Item $TlsKeyPath $keyFile
        Write-Ok "Custom TLS certificates installed"
    } else {
        Write-Info "Generating self-signed TLS certificates via Docker..."
        docker run --rm -v "${certDir}:/certs" alpine/openssl req -x509 -nodes -days 365 `
            -newkey rsa:2048 `
            -keyout /certs/server.key `
            -out /certs/server.crt `
            -subj "/C=US/ST=State/L=City/O=SecureLLM/CN=securellm.local" 2>$null

        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Self-signed certificates generated (valid 365 days)"
            Write-Warn "Replace with real certificates for production use."
        } else {
            Write-Warn "Could not generate TLS certificates. Generate them manually."
        }
    }
}

function Copy-Files {
    Write-Info "Copying files..."

    $scriptDir = Split-Path -Parent $MyInvocation.ScriptName

    # Copy engine source
    if (Test-Path (Join-Path $scriptDir "engine")) {
        Copy-Item -Recurse -Force (Join-Path $scriptDir "engine\*") (Join-Path $InstallDir "engine\")
    }

    # Copy bridge source
    $bridgeDest = Join-Path $InstallDir "bridge"
    if (-not (Test-Path $bridgeDest)) { New-Item -ItemType Directory -Path $bridgeDest | Out-Null }
    if (Test-Path (Join-Path $scriptDir "bridge")) {
        Copy-Item -Recurse -Force (Join-Path $scriptDir "bridge\*") $bridgeDest
        Write-Ok "NATS bridge copied"
    }

    # Copy NATS leaf node config
    $natsDest = Join-Path $InstallDir "nats"
    if (-not (Test-Path $natsDest)) { New-Item -ItemType Directory -Path $natsDest | Out-Null }
    if (Test-Path (Join-Path $scriptDir "nats")) {
        Copy-Item -Recurse -Force (Join-Path $scriptDir "nats\*") $natsDest
        Write-Ok "NATS leaf node config copied"
    }

    # Copy compose file
    Copy-Item -Force (Join-Path $scriptDir "docker-compose.prod.yml") (Join-Path $InstallDir "docker-compose.yml")

    # Copy nginx
    $nginxDest = Join-Path $InstallDir "nginx"
    if (-not (Test-Path $nginxDest)) { New-Item -ItemType Directory -Path $nginxDest | Out-Null }
    Copy-Item -Recurse -Force (Join-Path $scriptDir "nginx\*") $nginxDest

    # Copy management script
    Copy-Item -Force (Join-Path $scriptDir "securellm.ps1") (Join-Path $InstallDir "securellm.ps1")

    Write-Ok "Files copied"
}

function Start-Services {
    Write-Info "Starting SecureLLM services..."

    Push-Location $InstallDir
    docker compose --env-file config\.env up -d --build
    Pop-Location

    Write-Info "Waiting for services to be ready..."
    $retries = 30
    while ($retries -gt 0) {
        try {
            $null = Invoke-WebRequest -Uri "https://localhost:$Port/health" -SkipCertificateCheck -TimeoutSec 2 -ErrorAction SilentlyContinue
            break
        } catch {
            $retries--
            Start-Sleep -Seconds 2
        }
    }

    if ($retries -eq 0) {
        Write-Warn "Services may still be starting. Check: .\securellm.ps1 status"
    } else {
        Write-Ok "All services are running"
    }
}

function Write-Summary {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Installation Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Access URL:    https://localhost:$Port"
    Write-Host "  Health Check:  https://localhost:$Port/health"
    Write-Host "  API Docs:      https://localhost:$Port/docs"
    Write-Host ""
    Write-Host "  Management:" -ForegroundColor White
    Write-Host "    .\securellm.ps1 status     - Check service status"
    Write-Host "    .\securellm.ps1 logs       - View logs"
    Write-Host "    .\securellm.ps1 stop       - Stop services"
    Write-Host "    .\securellm.ps1 restart    - Restart services"
    Write-Host "    .\securellm.ps1 backup     - Backup data"
    Write-Host "    .\securellm.ps1 update     - Pull latest version"
    Write-Host ""
    Write-Host "  Config:        $InstallDir\config\.env"
    Write-Host "  Backups:       $InstallDir\backups\"
    Write-Host ""
}

# === Main ===
Write-Header
Test-Prerequisites
Initialize-Directories
Initialize-Config
Initialize-TLS
Copy-Files
Start-Services
Write-Summary
