[commit-checks-badge]: https://github.com/conda-incubator/conda-recipe-manager/actions/workflows/commit_checks.yaml/badge.svg?branch=main
[integration-tests-badge]: https://github.com/conda-incubator/conda-recipe-manager/actions/workflows/integration_tests.yaml/badge.svg?branch=main
[release-badge]: https://img.shields.io/github/v/release/conda-incubator/conda-recipe-manager?logo=github


# `conda-recipe-manager`

[![Commit Checks][commit-checks-badge]](https://github.com/conda-incubator/conda-recipe-manager/actions/workflows/commit_checks.yaml)
[![Integration Tests][integration-tests-badge]](https://github.com/conda-incubator/conda-recipe-manager/actions/workflows/integration_tests.yaml)
[![GitHub Release][release-badge]](https://github.com/conda-incubator/conda-recipe-manager/releases)

# Overview
Conda Recipe Manager (CRM) is a library and tool-set capable of managing `conda` recipe files. It is intended
to be used by package builders and developers to automate the generation and editing of `conda` recipe files.

The most mature portion of this project is the `parser` module, that allows developers to parse, render, and edit
existing recipe files. There is also some on-going work for parsing recipe selectors and Conda Build Config files.

For a more comprehensive break-down and status of the library modules, see
[this document](./conda_recipe_manager/README.md).

## Recipe Compatibility
The latest recipe-parsing compatibility statistics can be found in the summary of our automated
[Integration Tests](https://github.com/conda-incubator/conda-recipe-manager/actions).

Our integration test data set is available [here](https://github.com/conda-incubator/conda-recipe-manager-test-data)
and is based off of publicly available recipe files from various sources.

NOTE: CRM only officially supports recipe files in the V0. There is on-going work to add full support for editing
V1-formatted files.

<!-- TOC -->

- [conda-recipe-manager](#conda-recipe-manager)
- [Overview](#overview)
    - [Recipe Compatibility](#recipe-compatibility)
    - [History](#history)
- [Getting Started](#getting-started)
    - [General Installation](#general-installation)
    - [CLI Usage](#cli-usage)
    - [Developer Installation and Notes](#developer-installation-and-notes)
        - [Developer Documentation](#developer-documentation)
        - [Setup Troubleshooting](#setup-troubleshooting)
        - [Making Commits](#making-commits)
        - [Running pre-commit Checks Individually](#running-pre-commit-checks-individually)
        - [Release process](#release-process)
- [Special Thanks](#special-thanks)

<!-- /TOC -->

## History
This project started out as a recipe parsing library in Anaconda's
[percy](https://github.com/anaconda-distribution/percy) project. Some `git` history was lost during that transfer
process.

For those of you who come from `conda-forge`, you may associate CRM as "the tool that converts recipe files for
`rattler-build`". Admittedly, that was the first-use case of the parsing capabilities provided by in this library. In
the future, we aim to expand past that and offer a number of recipe automation tools and modules.

# Getting Started

## General Installation

To install the project to your current `conda` environment, run:
```sh
conda install -c conda-forge conda-recipe-manager
```
This will add the commands `conda-recipe-manager` and `crm` to your environment's path. Note that both of these
commands are the same. `crm` is provided for convenience of typing.

## CLI Usage
Although CRM is a library, it does ship with a handful of command line tools. Running `crm --help` will provide a
an up-to-date listing of all available tools. Run `crm <tool-name> --help` for usage documentation about each tool.

The following usage message was last updated on 2024-10-31:
```sh
Usage: crm [OPTIONS] COMMAND [ARGS]...

  Command line interface for conda recipe management commands.

Options:
  -v, --verbose  Enables verbose logging (for commands that use the logger).
  --help         Show this message and exit.

Commands:
  bump-recipe         Bumps a recipe file to a new version.
  convert             Converts a `meta.yaml` formatted-recipe file to the new
                      `recipe.yaml` format.
  graph               Interactive CLI for examining recipe dependency graphs.
  patch               Modify recipe files with JSON patch blobs.
  rattler-bulk-build  Given a directory, performs a bulk rattler-build
                      operation. Assumes rattler-build is installed.
```

A high-level overview of the CLI tools can be found [here](./conda_recipe_manager/commands/README.md).

## Developer Installation and Notes
The `make dev` directive will configure a `conda` environment named `conda-recipe-manager` for you with
a development version of the tooling installed.

```sh
make dev
conda activate conda-recipe-manager
```

### Developer Documentation
We aim for a very high bar when it comes to code documentation so that we may leverage automatic documentation
workflows. API docs are hosted [here](https://conda-incubator.github.io/conda-recipe-manager/index.html)

### Setup Troubleshooting
- If you are currently in the `conda-recipe-manager` environment, make sure that you exit the environment with
  `conda deactivate` before running `make dev`. There have been known issues with attempting to delete the environment
  while an active instance is open.
- There have been known some issues using Berkley `make` (`bmake`) to setup the environment. The `Makefile` provided
  assumes GNU `make` is being used. This should only be an issue when running `make dev` as the `conda-recipe-manager`
  environment installs a version of GNU `make` to the environment.

### Making Commits
`pre-commit` is automatically installed and configured for you to run a number of automated checks on each commit. These
checks will also be strictly enforced by our automated GitHub workflows.

This project uses modern Python type annotations and a strict set of `pylint` and `mypy` configurations to ensure code
quality. We use the `black` text formatter to prevent arguments over code style. We attempt to signify if a type,
variable, function, etc is `private`/`protected` with a single leading `_`.

### Running pre-commit Checks Individually
The provided `Makefile` also provides a handful of convenience directives for running all or part of the `pre-commit`
checks:

1. `make test`: Runs all the unit tests
1. `make test-cov`: Reports the current test coverage percentage and indicates which lines are currently untested.
1. `make lint`: Runs our `pylint` configuration, based on Google's Python standards.
1. `make format`: Automatically formats code
1. `make analyze`: Runs the static analyzer, `mypy`.
1. `make pre-commit`: Runs all the `pre-commit` checks on every file.

### Release process
Here is a brief overview of our current release process:
1. Update `CHANGELOG.md`
1. Update the version number in `pyproject.toml`, `docs/conf.py`, and `recipe/meta.yaml`
1. Ensure `environment.yaml` is up to date with the latest dependencies
1. Create a new release on GitHub with a version tag.
1. Manage the conda-forge feedstock, as per [this doc](https://conda-forge.org/docs/maintainer/adding_pkgs/)

# Special Thanks
- @cbouss for his work on the [Percy project](https://github.com/anaconda/percy) that originally inspired the recipe parser.
- @akabanovs for his work and experimentation on package dependency graph building.
- @JeanChristopheMorinPerso for his PR review contributions when this project was a part of `Percy` and answering questions about the `conda` file formats.
- @mrbean-bremen for maintaining the `pyfakefs` project and for providing guidance and assistance with `pyfakefs`.
