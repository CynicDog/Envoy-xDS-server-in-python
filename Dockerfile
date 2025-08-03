FROM python:3.13-slim

# Copy uv binaries from Astral's official uv image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y netcat-openbsd && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY pyproject.toml .
COPY uv.lock .

RUN uv pip install --system --requirements pyproject.toml

COPY . .

ENV PYTHONPATH=/app/proto/gen
ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "xds_server.py"]
