.PHONY: help build up down logs migrate seed createsuperuser test test-all test-e2e test-e2e-ui test-e2e-headed shell clean stop

help:
	@echo "CT Upload Platform - Available Commands"
	@echo "========================================"
	@echo ""
	@echo "Setup & Build:"
	@echo "  make build              - Build Docker images"
	@echo "  make up                 - Start all services (detached)"
	@echo "  make up-foreground      - Start all services in foreground"
	@echo "  make down               - Stop and remove containers"
	@echo "  make clean              - Stop containers and remove volumes"
	@echo ""
	@echo "Database:"
	@echo "  make migrate            - Run Django migrations"
	@echo "  make seed               - Seed protocol choices and scanner catalogue"
	@echo "  make createsuperuser    - Create a Django superuser"
	@echo ""
	@echo "Development:"
	@echo "  make test               - Run Django unit tests (237 tests)"
	@echo "  make test-all           - Run all tests (unit + E2E)"
	@echo "  make test-coverage      - Run unit tests with coverage report"
	@echo "  make test-e2e           - Run Playwright E2E tests"
	@echo "  make test-e2e-ui        - Run Playwright E2E tests with UI"
	@echo "  make test-e2e-headed    - Run Playwright E2E tests in browser"
	@echo "  make shell              - Open Django shell"
	@echo "  make bash               - Open bash in web container"
	@echo ""
	@echo "Utilities:"
	@echo "  make stop               - Stop services (without removing)"
	@echo "  make ps                 - Show running containers"
	@echo ""

build:
	docker compose build --pull

up:
	docker compose up -d
	@echo "✓ Services started in background"
	@echo "  - Web: http://localhost:8000"
	@echo "  - Admin: http://localhost:8000/admin"
	@echo "  - API docs: http://localhost:8000/api/v1/"
	@echo ""
	@echo "Run 'make logs' to view logs"

up-foreground:
	docker compose up

down:
	docker compose down
	@echo "✓ Services stopped"

stop:
	docker compose stop
	@echo "✓ Services stopped (containers preserved)"

clean:
	docker compose down -v
	@echo "✓ Services stopped and volumes removed"

logs:
	docker compose logs -f

ps:
	docker compose ps

migrate:
	docker compose exec web python manage.py migrate

seed:
	docker compose exec web python manage.py populate_protocol_choices
	docker compose exec web python manage.py create_scanner_profiles
	@echo "✓ Protocol choices and scanner catalogue seeded"

createsuperuser:
	docker compose exec -it web python manage.py createsuperuser

test:
	docker compose exec web python manage.py test uploads.tests --keepdb

test-all:
	@echo "Running all available tests..."
	@echo ""
	@echo "Phase 1: Running Django unit tests (237 tests)..."
	docker compose exec web python manage.py test uploads.tests --keepdb
	@echo ""
	@echo "✓ Django unit tests passed!"
	@echo ""
	@echo "Phase 2: Running Playwright E2E tests..."
	npx playwright test
	@echo ""
	@echo "✓ All tests completed successfully!"

test-e2e:
	npx playwright test

test-e2e-ui:
	npx playwright test --ui

test-e2e-headed:
	npx playwright test --headed

test-coverage:
	docker compose exec web coverage run --source='uploads' manage.py test uploads.tests
	docker compose exec web coverage report

shell:
	docker compose exec -it web python manage.py shell

bash:
	docker compose exec -it web /bin/bash

shell-db:
	docker compose exec -it db psql -U $${DB_USER:-postgres} -d $${DB_NAME:-ct_upload_platform}

redis-cli:
	docker compose exec -it redis redis-cli

create-token:
	@read -p "Enter username: " username; \
	docker compose exec web python manage.py create_upload_token $$username

collectstatic:
	docker compose exec web python manage.py collectstatic --noinput

lint:
	docker compose exec web flake8 uploads

format:
	docker compose exec web black uploads

requirements:
	pip freeze > requirements.txt

dev-install:
	@echo "Installing development dependencies..."
	pip install -r requirements.txt
	@echo "✓ Dependencies installed"

dev-up:
	python manage.py runserver 0.0.0.0:8000

dev-test:
	python manage.py test uploads.tests

dev-migrations:
	python manage.py makemigrations
	python manage.py migrate

# Docker debugging
docker-logs-web:
	docker logs -f ct_upload_web

docker-logs-worker:
	docker logs -f ct_upload_worker

docker-logs-db:
	docker logs -f ct_upload_db

docker-logs-redis:
	docker logs -f ct_upload_redis

# Database utilities
db-backup:
	mkdir -p backups
	docker compose exec -T db pg_dump -U $${DB_USER:-postgres} $${DB_NAME:-ct_upload_platform} > backups/db_backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "✓ Database backed up"

db-restore:
	@read -p "Enter backup filename: " backup_file; \
	docker compose exec -T db psql -U $${DB_USER:-postgres} $${DB_NAME:-ct_upload_platform} < $$backup_file; \
	echo "✓ Database restored"

# Development helpers
watch-logs:
	watch -n 1 'docker compose logs --tail=20'

restart:
	docker compose restart
	@echo "✓ Services restarted"

rebuild:
	docker compose down -v
	docker compose build --no-cache
	docker compose up -d
	@echo "✓ Services rebuilt and started"

# Admin console
admin:
	@echo "Opening Django admin at http://localhost:8000/admin"
	@open http://localhost:8000/admin || xdg-open http://localhost:8000/admin || echo "Open http://localhost:8000/admin in your browser"

# Status check
status:
	@echo "Container Status:"
	@docker compose ps
	@echo ""
	@echo "Service Health:"
	@docker compose exec -T db pg_isready -U $${DB_USER:-postgres} > /dev/null 2>&1 && echo "✓ Database: OK" || echo "✗ Database: DOWN"
	@docker compose exec -T redis redis-cli ping > /dev/null 2>&1 && echo "✓ Redis: OK" || echo "✗ Redis: DOWN"
	@curl -s http://127.0.0.1:8003/admin/ > /dev/null && echo "✓ Web: OK" || echo "✗ Web: DOWN"
