Welcome to leanclient's Documentation
=====================================

Overview
--------

leanclient is a thin wrapper around the native Lean language server.
It enables interaction with a Lean language server instance running in a subprocess.

Check out the `github repository <https://github.com/oOo0oOo/leanclient>`_ for more information.


Key Features
------------

- **Interact**: Query and change lean files via the `LSP <https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/>`_
- **Thin wrapper**: Directly expose the `Lean Language Server <https://github.com/leanprover/lean4/tree/master/src/Lean/Server>`_.
- **Fast**: Typically more than 95% of time is spent waiting.
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
   file_path = "MyProject/Basic.lean")
   result = client.get_goal(file_path, line=0, character=2)
   print(result)

   # Use a SingleFileClient for simplified interaction with a single file.
   sfc = client.create_file_client(file_path)
   result = sfc.get_term_goal(line=0, character=5)
   print(result)

   # Make a change to the document.
   change = lc.DocumentContentChange(text="-- Adding a comment at the head of the file\n", start=[0, 0], end=[0, 0])
   sfc.update_file(changes=[change])

   # Check the document content as seen by the LSP (changes are not written to disk).
   print(sfc.get_file_content())


.. toctree::
   :maxdepth: 2
   :caption: Contents

   benchmarks
   limitations
   api
