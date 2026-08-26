# backend/Dockerfile
# Uses python:3.11-slim (NOT alpine) — PaddleOCR requires glibc native libs.

FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (UID 1000)
RUN groupadd -r sovereign && useradd -r -g sovereign -u 1000 sovereign

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY --chown=sovereign:sovereign . .

# Create required data directories with correct ownership
RUN mkdir -p /app/data/sqlite /app/data/uploads /app/data/sandbox_workspace \
    && chown -R sovereign:sovereign /app/data

USER sovereign

EXPOSE 8000

# Run migrations then start server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1"]
