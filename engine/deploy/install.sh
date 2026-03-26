#!/usr/bin/env bash
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
BOLD='\033[1m'

INSTALL_DIR="${SECURELLM_INSTALL_DIR:-/opt/securellm}"
COMPOSE_FILE="docker-compose.prod.yml"

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

header() {
    echo ""
    echo -e "${BOLD}========================================${NC}"
    echo -e "${BOLD}  SecureLLM Privacy Gateway${NC}"
    echo -e "${BOLD}  Enterprise On-Premise Installer${NC}"
    echo -e "${BOLD}========================================${NC}"
    echo ""
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    local missing=0

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        missing=1
    else
        log_ok "Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
    fi

    if ! docker compose version &> /dev/null 2>&1; then
        if ! command -v docker-compose &> /dev/null; then
            log_error "Docker Compose is not installed."
            missing=1
        else
            log_ok "Docker Compose (standalone)"
        fi
    else
        log_ok "Docker Compose (plugin)"
    fi

    if ! command -v openssl &> /dev/null; then
        log_warn "OpenSSL not found. Self-signed certs will be skipped."
    else
        log_ok "OpenSSL $(openssl version | awk '{print $2}')"
    fi

    if [ $missing -eq 1 ]; then
        log_error "Missing prerequisites. Aborting."
        exit 1
    fi

    echo ""
}

generate_random() {
    local length=${1:-32}
    openssl rand -hex "$((length / 2))" 2>/dev/null || \
        head -c "$length" /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c "$length"
}

setup_directories() {
    log_info "Setting up directories at ${INSTALL_DIR}..."

    mkdir -p "${INSTALL_DIR}"/{config,data/redis,certs,logs,backups,engine}

    log_ok "Directory structure created"
}

configure() {
    local env_file="${INSTALL_DIR}/config/.env"

    if [ -f "$env_file" ] && [ "${FORCE_RECONFIGURE:-0}" != "1" ]; then
        log_warn "Configuration already exists. Use FORCE_RECONFIGURE=1 to overwrite."
        return
    fi

    log_info "Configuring SecureLLM..."
    echo ""

    # License Key
    local license_key="${SECURELLM_LICENSE_KEY:-}"
    if [ -z "$license_key" ]; then
        echo -e "${YELLOW}Enter your SecureLLM license key (provided by your vendor):${NC}"
        read -r license_key
        echo ""
    fi

    # Admin API Key
    local admin_api_key="${ADMIN_API_KEY:-}"
    if [ -z "$admin_api_key" ]; then
        echo -e "${YELLOW}Enter an Admin API key (or press Enter to auto-generate):${NC}"
        read -r admin_api_key
        echo ""
    fi
    if [ -z "$admin_api_key" ]; then
        admin_api_key="$(generate_random 40)"
    fi

    # Workspace ID (assigned by admin on Railway SaaS)
    local workspace_id="${WORKSPACE_ID:-}"
    if [ -z "$workspace_id" ]; then
        echo -e "${YELLOW}Enter your Workspace ID (assigned by the admin on Railway):${NC}"
        read -r workspace_id
        echo ""
    fi

    # Auto-generate secrets
    local api_secret_key
    api_secret_key="$(generate_random 64)"

    local redis_password
    redis_password="$(generate_random 32)"

    local instance_id
    instance_id="$(hostname)-$(generate_random 8)"

    local local_nats_token
    local_nats_token="$(generate_random 32)"

    # Port
    local https_port="${HTTPS_PORT:-443}"

    # Write .env
    cat > "$env_file" << EOF
# SecureLLM On-Premise Configuration
# Generated on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# DO NOT share this file — it contains secrets.

# === Redis ===
REDIS_URL=redis://:${redis_password}@redis:6379/0
REDIS_PASSWORD=${redis_password}

# === Auth ===
API_SECRET_KEY=${api_secret_key}
ADMIN_API_KEY=${admin_api_key}

# === Presidio ===
PRESIDIO_EXTERNAL_URL=

# === Server ===
HOST=0.0.0.0
PORT=8000

# === On-Premise Settings ===
DEPLOYMENT_MODE=onprem
LICENSE_KEY=${license_key}
SAAS_URL=https://securellm.railway.app
INSTANCE_ID=${instance_id}

# === NATS Tunnel ===
LOCAL_NATS_TOKEN=${local_nats_token}
SAAS_NATS_URL=${SAAS_NATS_URL:-wss://securellm.railway.app:443/nats}
WORKSPACE_ID=${workspace_id}
NATS_CREDENTIALS=
ENGINE_URL=http://engine:8000
NATS_URL=nats://nats-leaf:4222
HEARTBEAT_INTERVAL=30
ENGINE_VERSION=1.0.0

# === Networking (for Docker Compose) ===
HTTPS_PORT=${https_port}
EOF

    chmod 600 "$env_file"

    log_ok "Configuration written to ${env_file}"
    echo ""
    echo -e "  ${BOLD}Admin API Key:${NC}     ${admin_api_key}"
    echo -e "  ${BOLD}Instance ID:${NC}       ${instance_id}"
    echo -e "  ${BOLD}Workspace ID:${NC}      ${workspace_id}"
    echo -e "  ${BOLD}HTTPS Port:${NC}        ${https_port}"
    echo ""
    echo -e "  ${YELLOW}Save these credentials securely. They won't be shown again.${NC}"
    echo ""
}

setup_tls() {
    local cert_dir="${INSTALL_DIR}/certs"

    if [ -f "${cert_dir}/server.crt" ] && [ "${FORCE_RECONFIGURE:-0}" != "1" ]; then
        log_ok "TLS certificates already exist"
        return
    fi

    if [ -n "${TLS_CERT_PATH:-}" ] && [ -n "${TLS_KEY_PATH:-}" ]; then
        log_info "Using provided TLS certificates..."
        cp "$TLS_CERT_PATH" "${cert_dir}/server.crt"
        cp "$TLS_KEY_PATH" "${cert_dir}/server.key"
        log_ok "Custom TLS certificates installed"
    elif command -v openssl &> /dev/null; then
        log_info "Generating self-signed TLS certificates..."
        openssl req -x509 -nodes -days 365 \
            -newkey rsa:2048 \
            -keyout "${cert_dir}/server.key" \
            -out "${cert_dir}/server.crt" \
            -subj "/C=US/ST=State/L=City/O=SecureLLM/CN=securellm.local" \
            2>/dev/null
        chmod 600 "${cert_dir}/server.key"
        log_ok "Self-signed certificates generated (valid 365 days)"
        log_warn "Replace with real certificates for production use."
    else
        log_warn "Cannot generate TLS certificates. HTTPS will not be available."
    fi
}

copy_compose() {
    log_info "Setting up Docker Compose configuration..."

    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Copy compose file
    cp "${script_dir}/docker-compose.prod.yml" "${INSTALL_DIR}/docker-compose.yml"
    cp -r "${script_dir}/nginx" "${INSTALL_DIR}/nginx"
    cp "${script_dir}/securellm.sh" "${INSTALL_DIR}/securellm.sh"
    chmod +x "${INSTALL_DIR}/securellm.sh"

    # Copy engine source (needed for Docker build)
    if [ -d "${script_dir}/engine" ]; then
        cp -r "${script_dir}/engine" "${INSTALL_DIR}/engine"
        log_ok "Engine source copied"
    fi

    # Copy bridge source (needed for Docker build)
    if [ -d "${script_dir}/bridge" ]; then
        cp -r "${script_dir}/bridge" "${INSTALL_DIR}/bridge"
        log_ok "NATS bridge copied"
    fi

    # Copy NATS leaf node config (needed for Docker build)
    if [ -d "${script_dir}/nats" ]; then
        cp -r "${script_dir}/nats" "${INSTALL_DIR}/nats"
        log_ok "NATS leaf node config copied"
    fi

    # Symlink management script to /usr/local/bin if possible
    if [ -d /usr/local/bin ] && [ -w /usr/local/bin ]; then
        ln -sf "${INSTALL_DIR}/securellm.sh" /usr/local/bin/securellm
        log_ok "Management CLI installed: 'securellm' command available"
    fi

    log_ok "Docker Compose configured"
}

start_services() {
    log_info "Starting SecureLLM services..."

    cd "${INSTALL_DIR}"
    docker compose --env-file config/.env up -d --build

    echo ""
    log_info "Waiting for services to be ready..."

    local retries=30
    while [ $retries -gt 0 ]; do
        if curl -sk "https://localhost:${HTTPS_PORT:-443}/health" > /dev/null 2>&1; then
            break
        fi
        retries=$((retries - 1))
        sleep 2
    done

    if [ $retries -eq 0 ]; then
        log_warn "Services may still be starting. Check: securellm status"
    else
        log_ok "All services are running"
    fi
}

print_summary() {
    local port="${HTTPS_PORT:-443}"
    echo ""
    echo -e "${BOLD}========================================${NC}"
    echo -e "${GREEN}${BOLD}  Installation Complete!${NC}"
    echo -e "${BOLD}========================================${NC}"
    echo ""
    echo -e "  ${BOLD}Access URL:${NC}    https://localhost:${port}"
    echo -e "  ${BOLD}Health Check:${NC}  https://localhost:${port}/health"
    echo -e "  ${BOLD}API Docs:${NC}      https://localhost:${port}/docs"
    echo ""
    echo -e "  ${BOLD}Management:${NC}"
    echo -e "    securellm status     — Check service status"
    echo -e "    securellm logs       — View logs"
    echo -e "    securellm stop       — Stop services"
    echo -e "    securellm restart    — Restart services"
    echo -e "    securellm backup     — Backup data"
    echo -e "    securellm update     — Pull latest version"
    echo ""
    echo -e "  ${BOLD}Config:${NC}        ${INSTALL_DIR}/config/.env"
    echo -e "  ${BOLD}Backups:${NC}       ${INSTALL_DIR}/backups/"
    echo ""
}

# Main
header
check_prerequisites
setup_directories
configure
setup_tls
copy_compose
start_services
print_summary
