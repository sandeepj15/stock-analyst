#!/usr/bin/env bash
set -e

# Change directory to repository root
cd "$(dirname "$0")"

echo "========================================================"
echo " Starting SignalForge (1-Command Server Startup)"
echo "========================================================"

# 1. Initialize .env from .env.example if missing
if [ ! -f .env ]; then
    echo "Notice: .env not found. Creating default .env from .env.example..."
    cp .env.example .env
    # Generate random JWT and encryption secrets if available
    JWT_HEX=$(openssl rand -hex 32 2>/dev/null || python -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "signalforge-secret-jwt-token")
    ENC_HEX=$(openssl rand -hex 32 2>/dev/null || python -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "signalforge-secret-enc-token")
    sed -i.bak "s/^JWT_SECRET=.*/JWT_SECRET=${JWT_HEX}/" .env && rm -f .env.bak
    sed -i.bak "s/^ENCRYPTION_KEY=.*/ENCRYPTION_KEY=${ENC_HEX}/" .env && rm -f .env.bak
    echo "Initialized .env with generated security keys."
fi

# 2. Build and launch all services with Docker Compose
echo "Building and launching containers..."
docker compose up --build -d

echo ""
echo "========================================================"
echo " SignalForge is running successfully!"
echo "========================================================"
echo " Web UI:      http://localhost:3000"
echo " API Docs:    http://localhost:8000/docs"
echo " API Health:  http://localhost:8000/health/db"
echo ""
echo " Useful commands:"
echo "   View live logs:    docker compose logs -f"
echo "   Check status:      docker compose ps"
echo "   Stop services:     docker compose down"
echo "========================================================"
