#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${SECURELLM_INSTALL_DIR:-/opt/securellm}"
ENV_FILE="${INSTALL_DIR}/config/.env"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
BOLD='\033[1m'

cd "${INSTALL_DIR}"

case "${1:-help}" in
    start)
        echo -e "${BLUE}Starting SecureLLM...${NC}"
        docker compose --env-file "$ENV_FILE" up -d
        echo -e "${GREEN}Started.${NC}"
        ;;

    stop)
        echo -e "${YELLOW}Stopping SecureLLM...${NC}"
        docker compose --env-file "$ENV_FILE" down
        echo -e "${GREEN}Stopped.${NC}"
        ;;

    restart)
        echo -e "${BLUE}Restarting SecureLLM...${NC}"
        docker compose --env-file "$ENV_FILE" down
        docker compose --env-file "$ENV_FILE" up -d
        echo -e "${GREEN}Restarted.${NC}"
        ;;

    status)
        echo -e "${BOLD}SecureLLM Service Status${NC}"
        echo "---"
        docker compose --env-file "$ENV_FILE" ps
        echo ""

        # Health check
        local_port=$(grep "HTTPS_PORT" "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "443")
        if curl -sk "https://localhost:${local_port}/health" > /dev/null 2>&1; then
            echo -e "Health: ${GREEN}Healthy${NC}"
        else
            echo -e "Health: ${RED}Unhealthy${NC}"
        fi
        ;;

    logs)
        service="${2:-}"
        if [ -n "$service" ]; then
            docker compose --env-file "$ENV_FILE" logs -f "$service"
        else
            docker compose --env-file "$ENV_FILE" logs -f
        fi
        ;;

    update)
        echo -e "${BLUE}Updating SecureLLM...${NC}"
        docker compose --env-file "$ENV_FILE" pull
        docker compose --env-file "$ENV_FILE" up -d --build
        echo -e "${GREEN}Updated and restarted.${NC}"
        ;;

    backup)
        backup_dir="${INSTALL_DIR}/backups"
        timestamp=$(date +%Y%m%d_%H%M%S)
        backup_file="${backup_dir}/securellm_backup_${timestamp}.tar.gz"

        echo -e "${BLUE}Creating backup...${NC}"

        # Backup config
        tar -czf "$backup_file" \
            -C "${INSTALL_DIR}" \
            config/ \
            2>/dev/null || true

        # Backup Redis data
        redis_pass=$(grep REDIS_PASSWORD "$ENV_FILE" | cut -d= -f2)
        docker compose --env-file "$ENV_FILE" exec -T redis redis-cli -a "$redis_pass" BGSAVE 2>/dev/null || true
        sleep 2

        echo -e "${GREEN}Backup saved: ${backup_file}${NC}"

        # Cleanup old backups (keep last 10)
        ls -t "${backup_dir}"/securellm_backup_*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm
        echo -e "Kept last 10 backups."
        ;;

    rotate-key)
        echo -e "${YELLOW}Rotating Admin API key...${NC}"
        new_key=$(openssl rand -hex 20)
        sed -i "s/^ADMIN_API_KEY=.*/ADMIN_API_KEY=${new_key}/" "$ENV_FILE"
        docker compose --env-file "$ENV_FILE" restart engine
        echo -e "${GREEN}New Admin API key: ${new_key}${NC}"
        echo -e "${YELLOW}Update your clients with the new key.${NC}"
        ;;

    help|*)
        echo -e "${BOLD}SecureLLM Management CLI${NC}"
        echo ""
        echo "Usage: securellm <command> [options]"
        echo ""
        echo "Commands:"
        echo "  start          Start all services"
        echo "  stop           Stop all services"
        echo "  restart        Restart all services"
        echo "  status         Show service status and health"
        echo "  logs [service] View logs (optionally for a specific service)"
        echo "  update         Pull latest images and restart"
        echo "  backup         Backup configuration and data"
        echo "  rotate-key     Generate and apply a new Admin API key"
        echo "  help           Show this help"
        echo ""
        ;;
esac
