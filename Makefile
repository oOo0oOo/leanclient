.PHONY: build install test test-profile docs

build:
	uv build

install:
	uv sync --all-extras

test:
	uv run pytest -n auto

test-all:
	uv run pytest

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