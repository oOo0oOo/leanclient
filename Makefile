.PHONY: build install test test-profile docs

build:
	poetry build

install:
	poetry install

test:
	poetry run python tests/run_tests.py

test-profile:
	poetry run python tests/run_tests.py --profile

docs:
	poetry run sphinx-build -b html docs/source/ docs/build/

publish:
	poetry publish --build

publish-test:
	poetry publish --build --repository testpypi