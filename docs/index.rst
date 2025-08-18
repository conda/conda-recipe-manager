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
the CLI tools provided by this project or how to contribute to this project directly, please visit the
`CRM GitHub repository <https://github.com/conda/conda-recipe-manager>`_.

Notes about logging
===================
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
==================

* :ref:`modindex`
