.PHONY: build install test test-profile

build:
	poetry build

install:
	poetry install

test:
	poetry run python tests/run_tests.py

test-profile:
	poetry run python tests/run_tests.py --profile
