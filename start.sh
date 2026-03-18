#!/bin/bash

# Load environment variables from .env if present (for local dev)
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Default PORT if not set
PORT=${PORT:-10000}

echo "🚀 Starting Flask app on port $PORT"

# Run with gunicorn for production
exec gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --timeout 120 \
    --log-level info