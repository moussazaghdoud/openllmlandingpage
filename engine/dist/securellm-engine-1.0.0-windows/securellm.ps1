param(
    [Parameter(Position=0)]
    [string]$Command = "help",
    [Parameter(Position=1)]
    [string]$Arg = ""
)

$InstallDir = if ($env:SECURELLM_INSTALL_DIR) { $env:SECURELLM_INSTALL_DIR } else { "C:\SecureLLM" }
$EnvFile = Join-Path $InstallDir "config\.env"

Push-Location $InstallDir

switch ($Command) {
    "start" {
        Write-Host "Starting SecureLLM..." -ForegroundColor Blue
        docker compose --env-file $EnvFile up -d
        Write-Host "Started." -ForegroundColor Green
    }

    "stop" {
        Write-Host "Stopping SecureLLM..." -ForegroundColor Yellow
        docker compose --env-file $EnvFile down
        Write-Host "Stopped." -ForegroundColor Green
    }

    "restart" {
        Write-Host "Restarting SecureLLM..." -ForegroundColor Blue
        docker compose --env-file $EnvFile down
        docker compose --env-file $EnvFile up -d
        Write-Host "Restarted." -ForegroundColor Green
    }

    "status" {
        Write-Host "SecureLLM Service Status" -ForegroundColor Cyan
        Write-Host "---"
        docker compose --env-file $EnvFile ps
        Write-Host ""

        $port = (Select-String -Path $EnvFile -Pattern "HTTPS_PORT=(.+)" | ForEach-Object { $_.Matches.Groups[1].Value }) ?? "443"
        try {
            $health = Invoke-WebRequest -Uri "https://localhost:$port/health" -SkipCertificateCheck -TimeoutSec 5 -ErrorAction Stop
            Write-Host "Health: Healthy" -ForegroundColor Green
        } catch {
            Write-Host "Health: Unhealthy" -ForegroundColor Red
        }
    }

    "logs" {
        if ($Arg) {
            docker compose --env-file $EnvFile logs -f $Arg
        } else {
            docker compose --env-file $EnvFile logs -f
        }
    }

    "update" {
        Write-Host "Updating SecureLLM..." -ForegroundColor Blue
        docker compose --env-file $EnvFile pull
        docker compose --env-file $EnvFile up -d --build
        Write-Host "Updated and restarted." -ForegroundColor Green
    }

    "backup" {
        $backupDir = Join-Path $InstallDir "backups"
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupFile = Join-Path $backupDir "securellm_backup_$timestamp.zip"

        Write-Host "Creating backup..." -ForegroundColor Blue

        Compress-Archive -Path (Join-Path $InstallDir "config") -DestinationPath $backupFile -Force

        Write-Host "Backup saved: $backupFile" -ForegroundColor Green

        # Keep last 10 backups
        Get-ChildItem $backupDir -Filter "securellm_backup_*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 10 | Remove-Item -Force
        Write-Host "Kept last 10 backups."
    }

    "rotate-key" {
        Write-Host "Rotating Admin API key..." -ForegroundColor Yellow
        $bytes = New-Object byte[] 20
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $newKey = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ''

        (Get-Content $EnvFile) -replace "^ADMIN_API_KEY=.*", "ADMIN_API_KEY=$newKey" | Set-Content $EnvFile
        docker compose --env-file $EnvFile restart engine

        Write-Host "New Admin API key: $newKey" -ForegroundColor Green
        Write-Host "Update your clients with the new key." -ForegroundColor Yellow
    }

    default {
        Write-Host "SecureLLM Management CLI" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Usage: .\securellm.ps1 <command> [options]"
        Write-Host ""
        Write-Host "Commands:"
        Write-Host "  start          Start all services"
        Write-Host "  stop           Stop all services"
        Write-Host "  restart        Restart all services"
        Write-Host "  status         Show service status and health"
        Write-Host "  logs [service] View logs (optionally for a specific service)"
        Write-Host "  update         Pull latest images and restart"
        Write-Host "  backup         Backup configuration and data"
        Write-Host "  rotate-key     Generate and apply a new Admin API key"
        Write-Host "  help           Show this help"
        Write-Host ""
    }
}

Pop-Location
