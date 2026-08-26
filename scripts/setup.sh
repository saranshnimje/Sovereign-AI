#!/bin/bash
# setup.sh — First-time setup for Sovereign AI Workbench
# Usage: bash scripts/setup.sh

set -e

echo "=================================================="
echo "  Sovereign AI Workbench — First-time Setup"
echo "=================================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker is required but not installed. See https://docs.docker.com/get-docker/"; exit 1; }
command -v ollama >/dev/null 2>&1 || { echo "ERROR: Ollama is required but not installed. See https://ollama.ai"; exit 1; }
echo "  ✓ Docker"
echo "  ✓ Ollama"
echo ""

# Generate .env if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    # Generate a random SECRET_KEY
    if command -v python3 >/dev/null 2>&1; then
        SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    else
        # Fallback to openssl
        SECRET_KEY=$(openssl rand -hex 32)
    fi
    # Replace placeholder
    sed -i.bak "s/your-secret-key-here-minimum-32-characters-change-this/$SECRET_KEY/" .env
    rm -f .env.bak
    echo "  ✓ Generated .env with a new SECRET_KEY"
else
    echo "  ✓ .env already exists (skipping generation)"
fi
echo ""

# Pre-pull the Docker sandbox image
echo "Pulling sandbox base image (python:3.11-slim)..."
docker pull python:3.11-slim
echo "  ✓ Sandbox image ready"
echo ""

# Check Ollama models
echo "Checking Ollama models..."
if ollama list 2>/dev/null | grep -q "llama3.2"; then
    echo "  ✓ Chat model found"
else
    echo "  ℹ  Pulling llama3.2:3b (this may take a few minutes)..."
    ollama pull llama3.2:3b
fi

if ollama list 2>/dev/null | grep -q "nomic-embed"; then
    echo "  ✓ Embedding model found"
else
    echo "  ℹ  Pulling nomic-embed-text..."
    ollama pull nomic-embed-text
fi
echo ""

echo "=================================================="
echo "  Setup Complete!"
echo "=================================================="
echo ""
echo "Next steps:"
echo "  1. Make sure Ollama is running:  ollama serve"
echo "  2. Start the stack:              docker compose up --build -d"
echo "  3. Check health:                 curl http://localhost/api/v1/system/health"
echo "  4. Open browser:                 http://localhost"
echo ""
