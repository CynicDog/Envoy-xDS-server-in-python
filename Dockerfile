FROM python:3.13-slim

# Copy uv binaries from Astral's official uv image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml .
COPY uv.lock .

RUN uv pip install --system --requirements pyproject.toml

COPY . .

ENV PYTHONPATH=/app/proto/gen

CMD ["uv", "run", "xds_server.py"]
