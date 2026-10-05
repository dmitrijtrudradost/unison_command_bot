FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir "uv>=0.5,<1"

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY main.py ./

RUN uv sync --no-dev

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "python", "main.py"]
