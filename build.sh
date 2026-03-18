#!/bin/bash
set -e

echo "🔧 Starting build..."
echo "🐍 Python version: $(python --version)"

# Upgrade pip
python -m pip install --upgrade pip

# Install build tools GLOBALLY (not just in build isolation)
echo "🔨 Installing global build dependencies..."
pip install --no-cache-dir \
    "setuptools>=68.0.0" \
    "wheel>=0.42.0" \
    "pkginfo>=1.10.0"

# Install ffmpeg for whisper
echo "📦 Installing system packages..."
apt-get update -qq 2>/dev/null || true
apt-get install -y -qq ffmpeg 2>/dev/null || echo "⚠️ ffmpeg skipped"

# Install main requirements (everything except whisper)
echo "📦 Installing Python dependencies..."
pip install --prefer-binary --no-cache-dir -r requirements.txt

# ⚠️ Install whisper SEPARATELY with --no-build-isolation
echo "🎙️ Installing openai-whisper (with build isolation disabled)..."
pip install --no-cache-dir --no-build-isolation \
    "openai-whisper @ git+https://github.com/openai/whisper.git@v20231117" || {
    echo "⚠️ Whisper install failed, trying fallback version..."
    pip install --no-cache-dir --no-build-isolation \
        "openai-whisper>=20230314"
}

# Pre-download tiny whisper model (faster)
echo "⬇️ Pre-downloading whisper model: ${WHISPER_MODEL:-tiny}"
python -c "
import os, whisper, sys
model = os.getenv('WHISPER_MODEL', 'tiny')
print(f'Loading whisper {model}...')
try:
    whisper.load_model(model)
    print('✅ Model ready')
except Exception as e:
    print(f'⚠️ Model download failed: {e}')
    sys.exit(0)
" 2>&1 || true

echo "✅ Build completed successfully!"