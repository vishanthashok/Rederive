export PYTHONPATH := sdk:.

.PHONY: install test server worker ui demo scenarios tune up

install:
	pip install -e ".[server,dev]"
	cd ui && npm install

test:
	python -m pytest -q

server:
	REDERIVE_ALLOW_RESET=1 uvicorn server.app:app --reload --port 8000

worker:
	python -m server.workers.rebuild

ui:
	cd ui && npm run dev

demo:
	python -m demo_agent.support_agent

scenarios:
	python eval/run_scenarios.py

tune:
	python eval/tune_cutoff.py

up:
	docker compose up --build
