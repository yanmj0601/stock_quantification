FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency syncing
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin/:$PATH"

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Sync dependencies (including dev and market-data)
RUN uv sync --extra market-data --extra dev

# Copy application source code
COPY src ./src
COPY README.md pyproject.toml uv.lock ./

# Create data directory
RUN mkdir -p var

# Expose backend API port
EXPOSE 8000

# Run the API server with auto scheduler enabled
CMD ["uv", "run", "--extra", "market-data", "--extra", "dev", "evoquant", "--host", "0.0.0.0", "--port", "8000"]
