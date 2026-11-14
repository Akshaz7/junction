.PHONY: dev api db-up db-down test

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

api:
	uv run uvicorn server.app:app --reload --reload-dir server --reload-dir engine --port 8000

dev: db-up
	@trap 'kill 0' INT TERM EXIT; \
	uv run uvicorn server.app:app --reload --reload-dir server --reload-dir engine --port 8000 & \
	if [ -f web/package.json ]; then (cd web && npm run dev -- --port 5173) & fi; \
	wait

test:
	@dirs=""; for d in server tests engine pipeline vision; do [ -d $$d ] && dirs="$$dirs $$d"; done; \
	uv run pytest -q $$dirs
	@if [ -f web/package.json ]; then cd web && npm test --silent; fi
