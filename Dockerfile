# Single image shared by the `api` and `worker` services (docker-compose.yml
# picks the command per-service). Documented in README.md "Docker layout".
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip
# Pre-install CPU-only PyTorch so pip avoids pulling 3.5GB+ of unused CUDA/cuDNN GPU binaries
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY . .
RUN pip install --no-cache-dir -e ".[dev]"
RUN chmod +x scripts/docker-entrypoint.sh

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
