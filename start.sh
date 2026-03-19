#!/bin/bash
set -e

PORT=${PORT:-10000}
echo "🚀 Starting Flask app on port $PORT"

# Production server with gunicorn
exec gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --log-level info \
    --access-logfile -