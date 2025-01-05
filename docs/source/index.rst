Welcome to leanclient's Documentation
=====================================

Overview
--------

leanclient is a thin wrapper around the native Lean language server.
It enables interaction with a Lean language server instance running in a subprocess.

Check out the `github repository <https://github.com/oOo0oOo/leanclient>`_.

Key Features
------------

- **Interact**: Query and change lean files.
- **Thin wrapper**: Directly expose the `Lean Language Server <https://github.com/leanprover/lean4/tree/master/src/Lean/Server>`_ via the `LSP <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/>`_.
- **Synchronous**: Requests block until a response is received.
- **Fast**: During `make test-profile` more than 99% of time is spent waiting for a server response.


Work in Progress
----------------

**Not compatible** with Lean 4.15.0 (stable) yet.

- The API is not fully stable.
- There are many missing features.
- Needs more testing with different setups.


.. toctree::
   :maxdepth: 1
   :caption: Contents

   api
