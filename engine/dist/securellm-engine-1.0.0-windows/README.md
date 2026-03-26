# SecureLLM -- Enterprise On-Premise Deployment Guide

## Overview

SecureLLM is a multi-tenant privacy gateway that anonymizes sensitive data before it reaches any LLM provider. This package lets enterprise customers run the SecureLLM backend on their own infrastructure, while the frontend dashboard remains hosted on Railway (SaaS).

## Architecture

```
                    +-------------------------------------------+
                    |        Customer Infrastructure            |
                    |                                           |
  Users --HTTPS--> |  Nginx --> SecureLLM Engine --> Redis      |
                    |  (TLS)    (FastAPI+Presidio)  (sessions)  |
                    |                                           |
                    +-------------------------------------------+
                              |
                         HTTPS (anonymized text only)
                              |
                              v
                    +-------------------+
                    | SecureLLM SaaS    |
                    | (Railway frontend)|
                    +-------------------+
```

**Key security properties:**
- All PII stays within your infrastructure
- Only anonymized/tokenized text leaves your network
- Redis is on an internal Docker network (not exposed)
- TLS enforced for all external connections
- Containers run as non-root with read-only filesystem

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4 cores |
| RAM | 4 GB | 8 GB |
| Disk | 10 GB | 20 GB |
| OS | Linux (any distro) | Ubuntu 22.04 / RHEL 9 |
| Docker | 24.0+ | Latest |
| Docker Compose | v2.20+ | Latest |
| Network | Outbound HTTPS | -- |

## Quick Install (5 minutes)

```bash
# As root or with sudo
chmod +x install.sh
./install.sh
```

The installer will:
1. Check prerequisites (Docker, Docker Compose, OpenSSL)
2. Create `/opt/securellm/` directory structure
3. Ask for your license key and Admin API key (or auto-generate one)
4. Auto-generate all secrets (Redis password, API_SECRET_KEY, instance ID)
5. Generate self-signed TLS certificates
6. Copy engine source and start the service

**Save the Admin API key shown at the end.**

## Non-Interactive Install (for automation)

```bash
export SECURELLM_LICENSE_KEY="your-license-key"
export ADMIN_API_KEY="your-admin-key"
export HTTPS_PORT=8443
export SECURELLM_INSTALL_DIR=/opt/securellm
./install.sh
```

## Custom TLS Certificates

```bash
export TLS_CERT_PATH=/path/to/your/cert.pem
export TLS_KEY_PATH=/path/to/your/key.pem
./install.sh
```

Or replace them after installation:
```bash
cp your-cert.pem /opt/securellm/certs/server.crt
cp your-key.pem /opt/securellm/certs/server.key
securellm restart
```

## Configuration

The `.env` file at `/opt/securellm/config/.env` contains all settings. Key variables:

| Variable | Description |
|----------|-------------|
| `REDIS_URL` | Redis connection string (auto-configured) |
| `REDIS_PASSWORD` | Redis password (auto-generated) |
| `API_SECRET_KEY` | JWT signing key (auto-generated) |
| `ADMIN_API_KEY` | Admin authentication key |
| `PRESIDIO_EXTERNAL_URL` | External Presidio URL (leave empty for built-in) |
| `HOST` | Bind address (default: 0.0.0.0) |
| `PORT` | Application port (default: 8000) |
| `DEPLOYMENT_MODE` | Set to `onprem` |
| `LICENSE_KEY` | Your license key |
| `SAAS_URL` | SaaS frontend URL |
| `INSTANCE_ID` | Unique instance identifier (auto-generated) |
| `HTTPS_PORT` | External HTTPS port for nginx (default: 443) |

## Management

```bash
securellm status          # Check service health
securellm logs            # View all logs
securellm logs engine     # View engine logs only
securellm restart         # Restart all services
securellm stop            # Stop all services
securellm start           # Start all services
securellm backup          # Backup config and data
securellm update          # Pull latest version and restart
securellm rotate-key      # Generate new Admin API key
```

## API Endpoints

### Anonymize Text
```bash
curl -sk https://localhost/v1/anonymize \
  -H "Authorization: Bearer YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "John Smith from Acme Corp sent a report to sarah@acme.com"
  }'
```

### Deanonymize Text
```bash
curl -sk https://localhost/v1/deanonymize \
  -H "Authorization: Bearer YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "<PERSON_1> from <ORGANIZATION_1> sent a report to <EMAIL_1>",
    "session_id": "SESSION_ID_FROM_ANONYMIZE"
  }'
```

### Chat Completions (Anonymize + LLM + Deanonymize)
```bash
curl -sk https://localhost/v1/chat/completions \
  -H "Authorization: Bearer YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Summarize: John Smith from Acme Corp sent a report about Project Phoenix"}
    ]
  }'
```

### Health Check
```bash
curl -sk https://localhost/health
```

## Firewall Rules

| Direction | Port | Destination | Purpose |
|-----------|------|-------------|---------|
| Inbound | 443 (configurable) | SecureLLM server | User/API access |
| Outbound | 443 | securellm.railway.app | SaaS frontend communication |

No other ports need to be open. Redis is isolated on an internal Docker network.

## Troubleshooting

```bash
# Check if services are running
securellm status

# View engine logs for errors
securellm logs engine

# Check Redis connectivity
docker exec securellm-redis-1 redis-cli -a YOUR_REDIS_PASSWORD ping

# Restart everything
securellm restart
```

## Updating

```bash
securellm backup    # Always backup first
securellm update    # Pulls latest images and restarts
```
