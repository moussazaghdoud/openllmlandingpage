#!/bin/sh
set -e

CONF="/etc/nats/nats-leaf.conf"

# Substitute environment variables into config
sed -i "s|SAAS_NATS_URL|${SAAS_NATS_URL:-nats://localhost:7422}|g" "$CONF"
sed -i "s|LOCAL_NATS_TOKEN|${LOCAL_NATS_TOKEN:-local-dev-token}|g" "$CONF"

# Create credentials file from env var if provided
if [ -n "$NATS_CREDENTIALS" ]; then
    mkdir -p /etc/nats/creds
    echo "$NATS_CREDENTIALS" > /etc/nats/creds/workspace.creds
    chmod 600 /etc/nats/creds/workspace.creds
fi

exec nats-server -c "$CONF" "$@"
