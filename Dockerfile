FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY src/ src/

RUN uv sync --locked --no-dev

EXPOSE 8080

CMD ["uv", "run", "src/gobble.py"]
