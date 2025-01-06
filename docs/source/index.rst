Welcome to leanclient's Documentation
=====================================

Overview
--------

leanclient is a thin wrapper around the native Lean language server.
It enables interaction with a Lean language server instance running in a subprocess.

Check out the `github repository <https://leanclient.readthedocs.io>`_ for more information.


Key Features
------------

- **Interact**: Query and change lean files via the `LSP <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/>`_
- **Thin wrapper**: Directly expose the `Lean Language Server <https://github.com/leanprover/lean4/tree/master/src/Lean/Server>`_.
- **Synchronous**: Requests block until a response is received.
- **Fast**: Typically more than 99% of time is spent waiting.
- **Parallel**: Easy batch processing of files using all your cores.


Quickstart
----------

The easiest way to get started is to check out this minimal example in Google Colab:

`Open in Colab <https://colab.research.google.com/github/oOo0oOo/leanclient/blob/main/examples/getting_started_leanclient.ipynb>`_

Or try it locally:

1) Setup a new lean project or use an existing one. See the colab notebook for a basic Ubuntu setup.

2) Install the package:

.. code-block:: bash

   pip install leanclient

3) In your python code:

.. code-block:: python

   import leanclient as lc

   # Start a new client, point it to your lean project root (where lakefile.toml is located).
   PROJECT_PATH = "path/to/your/lean/project/root/"
   client = lc.LeanLSPClient(PROJECT_PATH)

   # Query a lean file in your project
   file_path = "MyProject/Basic.lean"
   result = client.get_goal(file_path, line=1, column=2)
   print(result)

   # Use a SingleFileClient for simplified interaction with a single file.
   sfc = client.create_file_client(file_path)
   result = sfc.get_term_goal(line=1, column=2)
   print(result)

   # Use a LeanClientPool for easy parallel processing multiple files.
   files = ["MyProject/Basic.lean", "Main.lean"]

   # Define a function that takes a SingleFileClient as its only parameter.
   def count_tokens(client: lc.SingleFileClient):
      return len(client.get_semantic_tokens())

   with lc.LeanClientPool(PROJECT_PATH, num_workers=8) as pool:
      results = pool.map(count_tokens, files)

      # Or use pool.submit() for increased control.
      futures = [pool.submit(count_tokens, path) for path in files]
      res_fut = [f.get() for f in futures]

   print(results)


Currently in Beta
-----------------

**Not compatible** with Lean 4.15.0 (stable) yet.

- The API is almost stable.
- There are missing features.
- Needs more testing with different setups.
- Any feedback is appreciated!


.. toctree::
   :maxdepth: 2
   :caption: Contents

   api
