COMPOSE_DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml
COMPOSE_PROD = docker compose -f docker-compose.yml -f docker-compose.prod.yml

.PHONY: init build up down restart logs ps migrate test lint dev-up prod-up health security-check

init:
	@command -v docker >/dev/null
	@docker compose version >/dev/null
	@bash scripts/init-env.sh

build: init
	$(COMPOSE_DEV) build

up:
	$(COMPOSE_DEV) up -d

down:
	$(COMPOSE_DEV) down

restart: down up

logs:
	$(COMPOSE_DEV) logs -f

ps:
	$(COMPOSE_DEV) ps

migrate:
	$(COMPOSE_DEV) run --rm backend alembic upgrade head

test:
	$(COMPOSE_DEV) run --rm backend pytest
	$(COMPOSE_DEV) run --rm frontend npm run test

lint:
	$(COMPOSE_DEV) run --rm backend ruff check .
	$(COMPOSE_DEV) run --rm frontend npm run lint

dev-up: init
	@PGPASSWORD=123456 bash scripts/check-postgres.sh
	$(COMPOSE_DEV) build
	$(COMPOSE_DEV) run --rm backend alembic upgrade head
	$(COMPOSE_DEV) up -d
	@for i in $$(seq 1 30); do curl -fsS http://127.0.0.1:8000/api/health >/dev/null && break; sleep 2; done
	@curl -fsS http://127.0.0.1:8000/api/health
	@wsl_ip=$$(hostname -I | awk '{print $$1}'); curl -fsS "http://$${wsl_ip}:8000/api/health"

prod-up: init
	$(COMPOSE_PROD) build
	$(COMPOSE_PROD) run --rm backend alembic upgrade head
	$(COMPOSE_PROD) up -d

health:
	curl -fsS http://127.0.0.1:8000/api/health

security-check:
	bash scripts/security-check.sh
