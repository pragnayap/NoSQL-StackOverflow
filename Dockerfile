FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project scripts
COPY etl/        ./etl/
COPY analytics/  ./analytics/
COPY bonus/      ./bonus/
COPY orchestrate.py .
COPY .env.template .

# Data folder mounted at runtime via volume
RUN mkdir -p /app/data/stacksample

# Health check — verifies Python environment is working
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import pymongo, neo4j, redis; print('ok')" || exit 1

# Default command (overridden per service in docker-compose.yml)
CMD ["python", "etl/load_mongodb.py"]
