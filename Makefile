.PHONY: build install test test-profile docs

build:
	uv build

install:
	uv sync --all-extras

test:
	uv run pytest -m "not slow and not benchmark"

test-all:
	uv run pytest

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration

test-parallel:
	uv run pytest -n auto

test-benchmark:
	uv run pytest tests/benchmark -v

test-coverage:
	uv run pytest --cov-report=html --cov-report=term
	@echo "Coverage report: htmlcov/index.html"

test-fast:
	uv run pytest -x -v

test-verbose:
	uv run pytest -vv

update-benchmark:
	uv run pytest tests/benchmark -v

docs:
	rm -rf docs/build/
	uv run sphinx-build -b html docs/source/ docs/build/

publish:
	uv build
	uv publish

publish-test:
	uv build
	uv publish --publish-url https://test.pypi.org/legacy/