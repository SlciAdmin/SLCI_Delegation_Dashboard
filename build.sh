#!/bin/bash
set -e

echo "🔧 Starting build..."
echo "🐍 Python version: $(python --version)"

# Upgrade pip
python -m pip install --upgrade pip

# Install build tools
pip install --no-cache-dir setuptools>=68.0.0 wheel>=0.42.0

# Install ffmpeg for whisper (ignore errors)
apt-get update -qq 2>/dev/null || true
apt-get install -y -qq ffmpeg 2>/dev/null || echo "⚠️ ffmpeg skipped"

# Install Python deps
echo "📦 Installing dependencies..."
pip install --prefer-binary --no-cache-dir -r requirements.txt

# Install whisper with no isolation (if not in requirements)
if ! pip show openai-whisper >/dev/null 2>&1; then
    echo "🎙️ Installing whisper..."
    pip install --no-cache-dir --no-build-isolation \
        "openai-whisper @ git+https://github.com/openai/whisper.git@v20231117" 2>/dev/null || true
fi

# Pre-download tiny whisper model
echo "⬇️ Pre-downloading whisper model: ${WHISPER_MODEL:-tiny}"
python -c "
import os, whisper, sys
model = os.getenv('WHISPER_MODEL', 'tiny')
try:
    whisper.load_model(model)
    print('✅ Model ready')
except:
    print('⚠️ Will download at runtime')
" 2>&1 || true

echo "✅ Build completed!"