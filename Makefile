.PHONY: build install test

build:
	pip install wheel
	python setup.py sdist bdist_wheel

install:
	pip install -e .[dev]

test:
	python tests/run_tests.py

test-profile:
	python tests/run_tests.py --profile