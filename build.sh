#!/bin/bash
set -e

echo "🔧 Starting build..."
echo "🐍 Python version: $(python --version)"

# Upgrade pip
python -m pip install --upgrade pip

# Install build tools
pip install --no-cache-dir setuptools>=68.0.0 wheel>=0.42.0

# Install Python deps
echo "📦 Installing dependencies..."
pip install --prefer-binary --no-cache-dir -r requirements.txt

echo "✅ Build completed!"