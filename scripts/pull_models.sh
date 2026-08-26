#!/bin/bash
# pull_models.sh — Pull recommended Ollama models
# Usage: bash scripts/pull_models.sh

echo "Pulling minimum required models..."
ollama pull llama3.2:3b
ollama pull nomic-embed-text

echo ""
echo "Pulling recommended medium models (optional, requires ~5GB RAM)..."
read -r -p "Pull mistral:7b-q4? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    ollama pull mistral:7b-q4
fi

read -r -p "Pull llava:7b-q4 (vision, optional)? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    ollama pull llava:7b-q4
fi

echo ""
echo "Available models:"
ollama list
