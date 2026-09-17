.PHONY: up down logs test lint run worker

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api worker

test:
	pytest -q

lint:
	ruff check .

run:
	uvicorn app.main:app --reload

worker:
	python -m app.worker

