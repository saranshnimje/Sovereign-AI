#!/bin/bash
# backup.sh — Backup all persistent Docker volumes
# Usage: bash scripts/backup.sh

set -e

BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up SQLite database and uploads..."
docker run --rm \
    -v sovereign-ai-workbench_backend_data:/data \
    -v "$(pwd)/$BACKUP_DIR":/backup \
    alpine \
    tar czf /backup/backend_data.tar.gz /data
echo "  ✓ Backend data backed up"

echo "Backing up Qdrant vector database..."
docker run --rm \
    -v sovereign-ai-workbench_qdrant_data:/data \
    -v "$(pwd)/$BACKUP_DIR":/backup \
    alpine \
    tar czf /backup/qdrant_data.tar.gz /data
echo "  ✓ Qdrant data backed up"

echo ""
echo "Backup complete: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"
