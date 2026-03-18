#!/bin/bash
set -e

echo "🔧 Starting build for Python 3.11..."

# Upgrade pip first
python -m pip install --upgrade pip

# Install system dependencies (ffmpeg for whisper)
echo "📦 Installing system packages..."
apt-get update -qq && apt-get install -y -qq ffmpeg > /dev/null 2>&1 || true

# Install Python deps: FORCE BINARY WHEELS (critical!)
echo "📦 Installing Python dependencies..."
pip install --prefer-binary --only-binary=:all: -r requirements.txt || {
    echo "⚠️ Binary install failed, trying fallback..."
    pip install --prefer-binary -r requirements.txt
}

# Pre-download whisper model (optional but recommended)
echo "⬇️ Pre-downloading whisper model: ${WHISPER_MODEL:-base}"
python -c "
import os, whisper
model = os.getenv('WHISPER_MODEL', 'base')
print(f'Loading whisper {model}...')
whisper.load_model(model)
print('✅ Model ready')
" 2>/dev/null || echo "⚠️ Whisper model will download at runtime"

echo "✅ Build completed successfully!"