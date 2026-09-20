.PHONY: help install verify test run api fit clean

help:
	@echo "install   create the virtual environment and install dependencies"
	@echo "verify    check the environment before relying on it"
	@echo "test      run the test suite"
	@echo "run       process the validation set end to end"
	@echo "api       start the HTTP interface"
	@echo "fit       derive the taxonomy and fit the calibration mapping"
	@echo "clean     remove generated artefacts (keeps the decision log)"

install:
	python3 -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r requirements.txt
	@echo "Now: cp .env.example .env and set OPENROUTER_API_KEY"

verify:
	python -m scripts.verify_setup

test:
	python -m pytest tests/ -v

run:
	python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results/

api:
	python -m src.api

fit:
	python -m scripts.build_taxonomy  --input data/development_tickets.json
	python -m scripts.fit_calibration --input data/development_tickets.json --sample 200
	python -m scripts.tune_thresholds --input data/development_tickets.json

clean:
	rm -rf evaluation/results __pycache__ .pytest_cache
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
