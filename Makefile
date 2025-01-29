.PHONY: build install test test-profile docs

build:
	poetry build

install:
	poetry install

test:
	poetry run python tests/run_tests.py

test-profile:
	poetry run python tests/run_tests.py --profile

test-all:
	poetry run python tests/run_tests.py --all

update-benchmark:
	poetry run python tests/run_tests.py --profile --benchmark
	cp tests/profile.png docs/source/profile_benchmark.png

docs:
	rm -rf docs/build/
	poetry run sphinx-build -b html docs/source/ docs/build/

publish:
	poetry publish --build

publish-test:
	poetry publish --build --repository testpypi