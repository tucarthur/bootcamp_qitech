#!/bin/bash
# Check if the stack is healthy

set -e

echo "🏥 Checking stack health..."

# Check containers
CONTAINERS=$(docker compose ps -q)
if [ -z "$CONTAINERS" ]; then
    echo "❌ No containers running. Start with: docker compose up"
    exit 1
fi

# Check API health
echo -n "   API: "
if curl -s http://localhost:3000/health_check > /dev/null 2>&1; then
    echo "✅ Healthy"
else
    echo "❌ Not responding"
    exit 1
fi

# Check database
echo -n "   Database: "
if docker compose exec db pg_isready -U bootcamp -d bootcamp > /dev/null 2>&1; then
    echo "✅ Healthy"
else
    echo "❌ Not responding"
    exit 1
fi

echo "✅ Stack is healthy and ready"
