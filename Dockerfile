FROM python:3.11-slim

# Installing system dependencies including gosu for privilege dropping
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copying and installing dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copying the application
COPY . /app

# Create directories (will be properly owned at runtime by entrypoint)
RUN mkdir -p /app/logs /app/data

# Copy entrypoint script and make executable
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Expose port monitoring
EXPOSE 9090

# Use entrypoint script (runs as root initially, drops to botuser)
ENTRYPOINT ["/docker-entrypoint.sh"]
