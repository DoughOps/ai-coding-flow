.PHONY: install run dev test clean docker-build docker-push

IMAGE      ?= khchiang1121/ai-coding-flow
SHA        := $(shell git rev-parse --short HEAD)

install:
	uv venv --python 3.13 .venv
	uv pip install -r requirements.txt
	uv tool install --force --python 3.12 aider-chat@latest
	npm install

run:
	uv run uvicorn server:app --env-file .env --port 8000

dev:
	uv run uvicorn server:app --env-file .env --port 8000 --reload

test:
	uv run pytest

clean:
	rm -rf .venv __pycache__ .pytest_cache node_modules

docker-build:
	docker build -t $(IMAGE):$(SHA) -t $(IMAGE):latest .

docker-push:
	docker push $(IMAGE):$(SHA)
	docker push $(IMAGE):latest

docker-run:
	docker run -p 8000:8000 --env-file .env $(IMAGE):latest