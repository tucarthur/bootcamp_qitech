# Local Development Guide

## Prerequisites

Make sure you have these installed:

| Tool | Purpose | Check |
|---|---|---|
| **Docker Desktop** | Run API and database | `docker compose version` |
| **Git** | Version control | `git --version` |
| **Python 3.11+** | Run tests locally | `python3 --version` |

## Getting Started

### 1. Clone and enter the project
```bash
git clone https://github.com/tucarthur/bootcamp_qitech.git
cd bootcamp_qitech
```

### 2. (Optional) Set environment variables
The defaults in `docker-compose.yml` work for local dev. If you need custom ports or secrets, copy the example:

```bash
cp .env.example .env
# Edit .env if needed (e.g., different port if 3000 is occupied)
```

### 3. Start the stack
```bash
docker compose up --build
```

Wait for the output `Application startup complete` — then the API is ready.

### 4. Verify it's working
```bash
curl http://localhost:3000/health_check
# Should return 204 No Content
```

## Running Tests

Tests run on your local Python, not in Docker. First time setup:

```bash
pip install -r requirements-dev.txt
```

Then run tests:
```bash
pytest
```

## Common Tasks

### View API logs
```bash
docker compose logs -f api
```

### View database logs
```bash
docker compose logs -f db
```

### Access the database directly
```bash
docker compose exec db psql -U bootcamp -d bootcamp
```

### Stop everything
```bash
docker compose down
```

### Stop everything and delete volumes (fresh start)
```bash
docker compose down -v
```

### Rebuild images (after dependency changes)
```bash
docker compose up --build
```

## Testing the API

### Create an entity
```bash
curl -X POST http://localhost:3000/sample_entity \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{
    "hello": "world",
    "name": "Test User",
    "email": "test@example.com",
    "document_number": "529.982.247-25",
    "birthdate": "1990-05-17"
  }'
```

### List entities
```bash
curl http://localhost:3000/sample_entities \
  -H "INTERNAL-TOKEN: default_token"
```

## Troubleshooting

### Port already in use
If port 3000 is occupied, set in `.env`:
```
API_PORT=3001
```

Then compose will listen on 3001 instead.

### Database fails to start
Check that port 5432 is free. If not, set in `.env`:
```
DB_PORT=5433
```

### Changes to code not reflected
The API has `--reload` enabled, so it restarts on file changes. Wait a moment and try again.

If it doesn't work, restart the container:
```bash
docker compose restart api
```

### Tests failing
Make sure the API and database are running:
```bash
docker compose ps
```

Both should show "healthy" or "Up". Then run:
```bash
pytest -v
```

## Documentation

- [README.md](README.md) — project overview and architecture
- [docker-compose.yml](docker-compose.yml) — service configuration
- [src/app.py](src/app.py) — FastAPI setup and routes
