# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libpq-dev \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application
COPY . /app

# Create directories (will be properly owned at runtime by entrypoint)
RUN mkdir -p /app/logs /app/data

# Copy entrypoint script and make executable
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Expose admin panel port
EXPOSE 9090

# Use entrypoint script (runs as root initially, drops to botuser)
ENTRYPOINT ["/docker-entrypoint.sh"]
