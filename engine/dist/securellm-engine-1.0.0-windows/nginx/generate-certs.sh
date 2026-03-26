#!/usr/bin/env bash
set -euo pipefail

CERT_DIR="${1:-./certs}"
DOMAIN="${2:-openllm.local}"

mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout "${CERT_DIR}/server.key" \
    -out "${CERT_DIR}/server.crt" \
    -subj "/C=US/ST=State/L=City/O=OpenLLM/CN=${DOMAIN}" \
    -addext "subjectAltName=DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1"

chmod 600 "${CERT_DIR}/server.key"
echo "Certificates generated in ${CERT_DIR}/"
