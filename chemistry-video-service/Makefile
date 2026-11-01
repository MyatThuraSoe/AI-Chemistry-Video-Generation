.PHONY: install run worker test test-e2e lint typecheck format demo docker-build docker-run

install:
	python -m pip install -e ".[dev]"

run:
	uvicorn app.main:app --reload

worker:
	python -m app.workers.runner

test:
	pytest tests/unit tests/integration

test-e2e:
	pytest tests/e2e -m e2e

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy app

demo:
	bash scripts/run_required_jobs.sh

docker-build:
	docker build -t chemistry-video-service .

docker-run:
	docker run --rm -p 8000:8000 chemistry-video-service
