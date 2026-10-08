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
# Install dependencies first (without the local package) so this layer is
# cached unless pyproject.toml changes.
RUN pip install --no-cache-dir --upgrade pip

COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
