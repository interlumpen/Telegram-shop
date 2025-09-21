FROM python:3.11-slim

# Installing system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copying and installing dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copying the application
COPY . /app

# Creating a user and directory
RUN useradd -m -u 1000 botuser \
    && mkdir -p /app/logs /app/data \
    && touch /app/logs/bot.log /app/logs/audit.log \
    && chown -R botuser:botuser /app

USER botuser

# Expose port monitoring
EXPOSE 9090

# Run with migrations
CMD bash -lc "alembic upgrade head && python run.py"