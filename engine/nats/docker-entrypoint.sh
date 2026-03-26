#!/bin/sh
set -e

CONF="/etc/nats/nats-leaf.conf"

# Copy to writable location
cp /nats-config/nats-leaf.conf "$CONF"

# Substitute environment variables into config
sed -i "s|SAAS_NATS_URL|${SAAS_NATS_URL:-nats://localhost:7422}|g" "$CONF"
sed -i "s|LOCAL_NATS_TOKEN|${LOCAL_NATS_TOKEN:-local-dev-token}|g" "$CONF"
sed -i "s|LEAFNODE_TOKEN|${LEAFNODE_TOKEN:-change-me}|g" "$CONF"

exec nats-server -c "$CONF" "$@"
