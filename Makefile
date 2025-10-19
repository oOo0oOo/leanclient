.PHONY: build install test test-profile docs

build:
	uv build

install:
	uv sync --all-extras

test:
	uv run python tests/run_tests.py

test-profile:
	uv run python tests/run_tests.py --profile

test-all:
	uv run python tests/run_tests.py --all

update-benchmark:
	uv run python tests/run_tests.py --profile --benchmark
	cp tests/profile.png docs/source/profile_benchmark.png

docs:
	rm -rf docs/build/
	uv run sphinx-build -b html docs/source/ docs/build/

publish:
	uv build
	uv publish

publish-test:
	uv build
	uv publish --publish-url https://test.pypi.org/legacy/