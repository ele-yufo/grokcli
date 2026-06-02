# grokcli — developer tasks. Zero runtime dependencies; tests use stdlib unittest.

PYTHON ?= python3

.PHONY: help test install dev-install uninstall clean

help:
	@echo "grokcli make targets:"
	@echo "  make test         Run the unittest suite"
	@echo "  make install      Install grokcli into the current environment (pip)"
	@echo "  make dev-install  Editable install (pip install -e .)"
	@echo "  make uninstall    Uninstall grokcli"
	@echo "  make clean        Remove caches and build artifacts"

test:
	$(PYTHON) -m unittest discover -t . -s grokcli -p 'test_*.py'

install:
	$(PYTHON) -m pip install .

dev-install:
	$(PYTHON) -m pip install -e .

uninstall:
	$(PYTHON) -m pip uninstall -y grokcli

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache
