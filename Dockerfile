FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Apply latest Debian security patches to reduce OS package CVEs
RUN apt-get update && \
  apt-get upgrade -y && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

RUN uv sync --frozen --no-dev --no-install-project

RUN DJANGO_SECRET_KEY=build-only-secret \
  POSTGRES_DB=build \
  POSTGRES_USER=build \
  POSTGRES_PASSWORD=build \
  POSTGRES_HOST=127.0.0.1 \
  POSTGRES_PORT=5432 \
  REDIS_URL=redis://127.0.0.1:6379/0 \
  uv run python manage.py collectstatic --noinput

RUN chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
