# Python Microservice Template

A production-grade Copier template for Python microservices built on FastAPI, SQLAlchemy 2.0, and Dishka DI.

## Usage

### Generate a new service

```bash
# Install copier
pip install copier

# Generate from this template
copier copy /path/to/python_service /path/to/new-service
```

You will be prompted for:

| Variable | Description | Default |
|----------|-------------|---------|
| `project_name` | Service name (kebab-case) | `my-service` |
| `project_description` | One-line description | `A Python microservice` |
| `server_port` | HTTP port | `5000` |
| `db_name` | PostgreSQL database name | derived from project_name |
| `python_version` | Python version | `3.13` |

### Non-interactive generation

```bash
copier copy /path/to/python_service /path/to/new-service \
  --data project_name=knowledge \
  --data project_description="Knowledge base service" \
  --data server_port=5002
```

### Run the generated project

```bash
cd /path/to/new-service
uv sync
uv run pytest -v
ENV=development uv run python -m app server run
```

### Update an existing project

When the template is updated, pull changes into a generated project:

```bash
cd /path/to/existing-service
copier update
```

## What's Included

- **Clean Architecture** -- Domain, Application, Infrastructure layers with strict separation
- **FastAPI + Dishka DI** -- Async endpoints with request-scoped dependency injection
- **SQLAlchemy 2.0** -- Async ORM with generic repository, Unit of Work, multi-tenant mixins
- **Layered YAML Config** -- default.yaml + {env}.yaml + .secrets.yaml + env var overrides
- **Auth** -- Keycloak provider + DevAuthProvider bypass for local development
- **Middleware** -- Correlation ID, rate limiting, audit logging, structured access logs
- **Background Tasks** -- DB-backed task queue with retry, poll loop, graceful shutdown
- **Service Client** -- httpx + exponential retry + circuit breaker + OAuth2 token caching
- **Pagination Framework** -- PaginationParams, CursorPaginationParams, SortParams, filter_dependency()
- **Testing** -- Unit (mocked UoW) + Integration (in-memory SQLite, httpx AsyncClient)
- **Docker** -- Multi-stage Dockerfile + docker-compose with PostgreSQL
- **Alembic** -- Async migrations with initial schema
