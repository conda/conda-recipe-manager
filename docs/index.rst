.. Conda Recipe Manager documentation master file, created by
   sphinx-quickstart on Mon Aug  5 10:59:49 2024.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Conda Recipe Manager
====================

**Latest Version:** |release|

Conda Recipe Manager (CRM) is a library and tool set capable of parsing conda recipe files. It is intended to be used
by package builders and developers to automate the generation and editing of conda recipe files.

This website acts as an API document for using conda-recipe-manager in other projects. For details about how to use
the CLI tools provided by this project or how to contribute to this project directly, please visit our |crm_github|.

.. |crm_github| raw:: html

   <a href=https://github.com/conda/conda-recipe-manager target="_blank">repository on GitHub</a>

Modules Overview
----------------
Here is a brief overview of all of the modules provided by Conda Recipe Manager, available as :code:`import conda_recipe_manager.<module>`.
A full over of all the modules provided can be found |crm_module_overview|.

.. |crm_module_overview| raw:: html

   <a href=https://github.com/conda/conda-recipe-manager/blob/main/conda_recipe_manager/README.md target="_blank">here</a>

* :code:`commands` - provides a set of command line interfaces that can be used to test-out and work with the primary features of the library without developing custom code.

* :code:`fetcher` - provides tools for fetching and normalizing remote resources. Files that are downloaded are done so using secure temporary directories.

* :code:`grapher` (WIP) - provides tools that are capable of plotting and understanding how recipe dependencies are related to each other.

* :code:`licenses` (WIP) - provides license file utilities.

* :code:`ops` - provides higher-level recipe editing tooling than what you might find in the :code:`parser` module. In other words, library components found in :code:`ops` tend to use :code:`parser` components.

* :code:`parser` - provides various tools to parse common conda recipe file formats and other conda-build constructs.

* :code:`scanner` (WIP) - provides tools for scanning files and other feedstock/recipe artifacts.

* :code:`utils` - provides general utilities that have no other sensible home and used by the other modules.


Notes about logging
-------------------
CRM uses the standard Python logging library. However, the library modules use the `NullHandler`, so no logs are emitted
by default. It is up to the client program to define a log handler.

A log handler is defined and used in the provided `crm` command line interface. By default, `WARNING`-level-and-above
messages are reported to `STDERR`. Use `crm --verbose` to see all the logs.

Contents
========

.. toctree::
   :maxdepth: 1

   usage
   modules

Indices and tables
------------------

* :ref:`modindex`
