#!/bin/bash
# Start the local development stack

set -e

echo "🚀 Starting the development stack..."
docker compose up --build

echo "✅ Stack is running"
echo "   API: http://localhost:3000"
echo "   Database: localhost:5432"
