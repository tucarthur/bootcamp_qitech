#!/bin/bash
# Run tests locally against the running API

set -e

echo "🧪 Running tests..."

# Check if containers are healthy
if ! docker compose ps | grep -q "healthy\|Up"; then
    echo "❌ API and database must be running. Start with: ./scripts/dev.sh"
    exit 1
fi

# Run pytest
pytest -v "$@"

echo "✅ Tests completed"
