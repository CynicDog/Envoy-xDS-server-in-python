FROM python:3.13-slim

# Copy uv binaries from Astral's official uv image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Buf CLI and necessary build dependencies
RUN apt-get update && \
    apt-get install -y netcat-openbsd curl && \
    curl -sSL https://github.com/bufbuild/buf/releases/download/v1.50.0/buf-$(uname -s)-$(uname -m) -o /usr/local/bin/buf && \
    chmod +x /usr/local/bin/buf && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY uv.lock .

RUN uv pip install --system --requirements pyproject.toml

# Copy project files
COPY . .

# Generate Protobuf files within the Docker image build
WORKDIR /app/proto
RUN buf generate
WORKDIR /app

# The generated files are now at /app/proto/gen
ENV PYTHONPATH=/app/proto/gen
ENV PYTHONUNBUFFERED=1

CMD ["python", "xds_server.py"]