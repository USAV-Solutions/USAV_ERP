# Docker Setup & Running Guide for USAV Inventory System

## Overview

The USAV Inventory System consists of:
- **PostgreSQL Database** - Data persistence
- **FastAPI Backend** - REST API server
- **React Frontend** - Web UI
- **pgAdmin** - Database management tool (optional)
- **Database Backups** - Automatic daily backups

## Prerequisites

Before running anything, ensure you have:
- [Docker](https://www.docker.com/products/docker-desktop) installed and running
- [Docker Compose](https://docs.docker.com/compose/) (comes with Docker Desktop)
- A `.env` file in the project root with the following variables:

```bash
# Database Configuration
DB_USER=postgres
DB_PASS=devpassword123
DB_NAME=inventory_system

# Debug & Environment
DEBUG=false
ENVIRONMENT=development

# Zoho Integration (Optional - leave empty if not using)
ZOHO_CLIENT_ID=
ZOHO_CLIENT_SECRET=
ZOHO_REFRESH_TOKEN=
ZOHO_ORGANIZATION_ID=

# pgAdmin (Optional)
PGADMIN_EMAIL=it@usavshop.com
PGADMIN_PASSWORD=admin
```

## Quick Start - Production Mode

Run the complete system with all services (database, backend, frontend):

```bash
docker-compose up -d
```

This will:
1. Build and start the PostgreSQL database
2. Run database migrations automatically
3. Build and start the FastAPI backend
4. Build and start the React frontend
5. Set up automatic daily backups

**Access the application:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Database: localhost:5432

## Development Mode

For development with hot reload on both backend and frontend:

```bash
docker-compose --profile dev up -d
```

This will:
- Start database, database backups normally
- Run backend with code reloading
- Run frontend with Vite hot reload
- Skip host `/mnt/product_images` mounts (not required in local dev)
- Run Zoho sync actions without image upload in dev UI by default
- Changes to code are reflected immediately without rebuilding

**Access:**
- Frontend (with hot reload): http://localhost:3000
- Backend API (with auto-reload): http://localhost:8000

## Running Individual Services

### Start only the database:
```bash
docker-compose up -d db
```

### Start database and backend (no frontend):
```bash
docker-compose up -d db backend
```

### Start only the frontend (assumes backend is running):
```bash
docker-compose up -d frontend
```

### Start development backend with production frontend:
```bash
docker-compose --profile dev up -d db backend-dev frontend
```

## Database Management

### Run database migrations:
```bash
docker-compose --profile migrate run migrations
```

### Access pgAdmin (database UI):
```bash
docker-compose --profile tools up -d pgadmin
```
Then visit: http://localhost:5050 (it@usavshop.com / admin)

### View database backups:
```bash
ls backups/
```

## Useful Commands

### View running containers:
```bash
docker-compose ps
```

### View logs:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f db

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Stop everything:
```bash
docker-compose down
```

### Stop and remove volumes (⚠️ deletes database):
```bash
docker-compose down -v
```

### Rebuild images (after dependency changes):
```bash
docker-compose build
docker-compose up -d
```

### Restart a service:
```bash
docker-compose restart frontend
```

### Access a container shell:
```bash
# Backend
docker-compose exec backend /bin/bash

# Frontend
docker-compose exec frontend /bin/sh

# Database
docker-compose exec db psql -U postgres -d inventory_system
```

## Troubleshooting

### Backend won't start / health check fails:
```bash
# Check logs
docker-compose logs backend

# Ensure migrations ran
docker-compose --profile migrate run migrations

# Restart backend
docker-compose restart backend
```

### Frontend shows "Cannot reach backend":
- Verify backend is running: `docker-compose ps`
- Check backend logs: `docker-compose logs backend`
- Ensure frontend can reach backend at http://backend:8000 (inside Docker network)

### Database connection issues:
- Check PostgreSQL is running: `docker-compose ps db`
- Verify environment variables in `.env` file
- Check if port 5432 is not already in use

### Hot reload not working in dev mode:
- Ensure volumes are correctly mounted
- Restart the container: `docker-compose --profile dev restart frontend-dev`

### `/mnt/product_images` missing on local machine:
- Dev profile no longer requires `/mnt/product_images`.
- `backend-dev` uses container-local `PRODUCT_IMAGES_PATH=/tmp/usav_product_images`.
- Product thumbnails/uploads are intentionally disabled in dev UI (`VITE_DISABLE_PRODUCT_IMAGES=true`).

### Out of disk space:
```bash
# Clean up unused images/containers
docker-compose down
docker system prune -a
```

## Port Configuration

If you need to change ports, edit `docker-compose.yml`:

```yaml
services:
  frontend:
    ports:
      - "3000:3000"  # Change first port number only
  backend:
    ports:
      - "8000:8000"  # e.g., "8001:8000" for port 8001
  db:
    ports:
      - "5432:5432"
```

Then restart: `docker-compose up -d`

## Production Deployment

For production, ensure:
1. Change all default passwords in `.env`
2. Set `ENVIRONMENT=production` and `DEBUG=false`
3. Use strong database passwords
4. Set up SSL/TLS reverse proxy (nginx/traefik)
5. Configure proper backup retention
6. Use secrets management for sensitive data

```bash
# Production start (without dev profiles)
docker-compose up -d
```

## Environment Variables Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `DB_USER` | postgres | PostgreSQL username |
| `DB_PASS` | devpassword123 | PostgreSQL password |
| `DB_NAME` | inventory_system | Database name |
| `DEBUG` | false | Enable debug mode |
| `ENVIRONMENT` | development | dev/production |
| `ZOHO_*` | (empty) | Zoho API credentials |
| `PGADMIN_*` | see above | pgAdmin credentials |

## Next Steps

1. Create `.env` file with your configuration
2. Run `docker-compose up -d` to start
3. Access frontend at http://localhost:3000
4. Check backend API docs at http://localhost:8000/docs
5. Monitor with `docker-compose logs -f`!