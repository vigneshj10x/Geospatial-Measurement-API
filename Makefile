.PHONY: help install run test lint docker-up docker-down format clean

help:
	@echo "Available commands:"
	@echo "  make install    - Install runtime and development dependencies"
	@echo "  make run        - Run local development server with auto-reload"
	@echo "  make test       - Execute full test suite with coverage report"
	@echo "  make lint       - Run Ruff static analysis and linter checks"
	@echo "  make docker-up  - Build and launch container stack with persistent volumes"
	@echo "  make docker-down- Stop and remove Docker containers"
	@echo "  make format     - Format and auto-fix code style with Ruff"

install:
	pip install --upgrade pip
	pip install -r requirements.txt -r requirements-dev.txt

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	python -m pytest --cov=app/services --cov-report=term-missing

lint:
	python -m ruff check .

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

format:
	python -m ruff check --fix .
	python -m ruff format .

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov __pycache__
