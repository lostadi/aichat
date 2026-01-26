#!/bin/bash
set -e

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
DOCKER_COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

# Check if docker-compose is available
if command -v docker-compose &> /dev/null; then
    CMD="docker-compose"
else
    CMD="docker compose"
fi

function show_help {
    echo "Usage: $0 [start|stop|status|restart|logs]"
}

if [ -z "$1" ]; then
    show_help
    exit 1
fi

case "$1" in
    start)
        echo "Starting SearXNG container..."
        $CMD -f "$DOCKER_COMPOSE_FILE" up -d
        echo "SearXNG started on http://localhost:8080"
        ;;
    stop)
        echo "Stopping SearXNG container..."
        $CMD -f "$DOCKER_COMPOSE_FILE" down
        echo "SearXNG stopped"
        ;;
    status)
        $CMD -f "$DOCKER_COMPOSE_FILE" ps
        ;;
    restart)
        $CMD -f "$DOCKER_COMPOSE_FILE" restart
        ;;
    logs)
        $CMD -f "$DOCKER_COMPOSE_FILE" logs -f
        ;;
    *)
        show_help
        exit 1
        ;;
esac
