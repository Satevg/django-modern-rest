FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY . .

RUN uv sync --extra pydantic --extra jwt --extra openapi

WORKDIR /app/django_test_app

EXPOSE 8080

CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8080"]
