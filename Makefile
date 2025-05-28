# The `.ONESHELL` and setting `SHELL` allows us to run commands that require `conda activate`
.ONESHELL:
SHELL := /bin/bash
# For GNU Make v4 and above, you must include the `-c` in order for `make` to find symbols from `PATH`
.SHELLFLAGS := -c -o pipefail -o errexit
CONDA_ACTIVATE = source $$(conda info --base)/etc/profile.d/conda.sh ; conda activate ; conda activate
# Ensure that we are using the python interpretter provided by the conda environment.
PYTHON3 := "$(CONDA_PREFIX)/bin/python3"

.PHONY: clean clean-build clean-env clean-test help dev pre-commit test test-cov lint format format-docs analyze docs
.DEFAULT_GOAL := help

CONDA_ENV_NAME ?= conda-recipe-manager
SRC_DIR = conda_recipe_manager
TEST_DIR = tests/
SCRIPTS_DIR = scripts/

# Auto-generated `make help` directives defined in this `Makefile`.
define BROWSER_PYSCRIPT
import os, webbrowser, sys

from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

BROWSER := python -c "$$BROWSER_PYSCRIPT"

clean: clean-test clean-build clean-env clean-docs ## Removes all build, test, coverage, and Python artifacts

clean-build: ## Removes build and Python artifacts
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-env:					## remove conda environment
        # In `conda@v25.5.0`, deletion of a non-existent conda environment returns an error code.
	if conda env list | grep -q "^$(CONDA_ENV_NAME) "; then \
		conda remove -y -n $(CONDA_ENV_NAME) --all; \
	fi

clean-test: ## Removes test, coverage, and profiler artifacts
	rm -fr .tox/
	rm -f .coverage
	rm -fr htmlcov/
	rm -fr .pytest_cache
	rm -rf reports/{*.html,*.png,*.js,*.css,*.json}
	rm -rf pytest.xml
	rm -rf pytest-coverage.txt
	rm -fr *.prof
	rm -fr profile.html profile.json

clean-docs:	## Removes temporary and auto-generated static doc files
	rm -rf docs/_autosummary
	rm -rf docs/_build

help:
	$(PYTHON3) -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

dev: clean		## Installs the package's development version to a fresh environment
	conda env create -f environment.yaml --name $(CONDA_ENV_NAME) --yes
	conda run --name $(CONDA_ENV_NAME) pip install -e .
	$(CONDA_ACTIVATE) $(CONDA_ENV_NAME) && pre-commit install

pre-commit:     ## Runs pre-commit against files.
	pre-commit run --all-files

test:			## Runs test cases
	$(PYTHON3) -m pytest -n auto --capture=no $(TEST_DIR)

test-cov:		## Checks test coverage requirements
	$(PYTHON3) -m pytest -n auto --cov-config=.coveragerc --cov=$(SRC_DIR) \
		$(TEST_DIR) --cov-fail-under=85 --cov-report term-missing

lint:			## Runs the linter against the project
	pylint --rcfile=.pylintrc $(SRC_DIR) $(TEST_DIR)

format:			## Runs the code auto-formatter
	isort --profile black --line-length=120 $(SRC_DIR) $(TEST_DIR) $(SCRIPTS_DIR)
	black --line-length=120 $(SRC_DIR) $(TEST_DIR) $(SCRIPTS_DIR)

format-docs:	## Runs the docstring auto-formatter. NOTE: this requires manually installing `docconvert` with `pip`
	docconvert --in-place --config .docconvert.json $(SRC_DIR)

analyze:		## Runs static analyzer on the project
	mypy --config-file=.mypy.ini --cache-dir=/dev/null $(SRC_DIR) $(TEST_DIR) $(SCRIPTS_DIR)

docs: clean-docs	## Generates static html documentation
	$(MAKE) -C docs html
