#!/bin/bash
# Follow logs from the running stack

SERVICE="${1:-api}"

case "$SERVICE" in
    api)
        echo "📋 Following API logs (Ctrl+C to stop)..."
        docker compose logs -f api
        ;;
    db)
        echo "📋 Following database logs (Ctrl+C to stop)..."
        docker compose logs -f db
        ;;
    all)
        echo "📋 Following all logs (Ctrl+C to stop)..."
        docker compose logs -f
        ;;
    *)
        echo "Usage: ./scripts/logs.sh [api|db|all]"
        echo "  api   - Follow API logs (default)"
        echo "  db    - Follow database logs"
        echo "  all   - Follow all logs"
        exit 1
        ;;
esac
