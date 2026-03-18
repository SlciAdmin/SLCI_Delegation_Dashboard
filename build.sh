#!/bin/bash
set -e

echo "🔧 Starting build..."
echo "🐍 Python version: $(python --version)"

# Upgrade pip FIRST
python -m pip install --upgrade pip

# Install build tools BEFORE requirements (critical for whisper!)
echo "🔨 Installing build dependencies..."
pip install --prefer-binary --no-cache-dir \
    setuptools>=68.0.0 \
    wheel>=0.42.0 \
    pkginfo>=1.10.0

# Install ffmpeg for whisper (ignore read-only filesystem errors)
echo "📦 Installing system packages..."
apt-get update -qq 2>/dev/null || true
apt-get install -y -qq ffmpeg 2>/dev/null || echo "⚠️ ffmpeg install skipped"

# Install Python deps: FORCE BINARY WHEELS
echo "📦 Installing Python dependencies..."
pip install --prefer-binary --no-cache-dir -r requirements.txt || {
    echo "❌ Install failed. Checking Python version..."
    python --version
    exit 1
}

# Pre-download whisper model (use tiny for faster build)
echo "⬇️ Pre-downloading whisper model: ${WHISPER_MODEL:-tiny}"
python -c "
import os, whisper, sys
model = os.getenv('WHISPER_MODEL', 'tiny')
print(f'Loading whisper {model}...')
try:
    whisper.load_model(model)
    print('✅ Model downloaded')
except Exception as e:
    print(f'⚠️ Model download failed: {e}')
    sys.exit(0)  # Don't fail build
" 2>&1 || true

echo "✅ Build completed successfully!"