.PHONY: up down logs migrate seed test lint typecheck web-build demo eval

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate:
	.venv/bin/alembic upgrade head

seed:
	.venv/bin/python -m backend.app.db.seed

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check backend

typecheck:
	.venv/bin/mypy backend/app

web-build:
	cd frontend && npm run build

demo: up
	@echo "Open http://localhost:3010 and sign in with operator@example.com / OperatorSecret123!"

eval:
	.venv/bin/python -m backend.app.evals.run
