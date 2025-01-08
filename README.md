<h1 align="center">
  leanclient
</h1>

<h4 align="center">Interact with the lean4 language server.</h4>

<p align="center">
  <a href="https://pypi.org/project/leanclient/">
    <img src="https://img.shields.io/pypi/v/leanclient.svg" alt="PyPI version" />
  </a>
  <a href="">
    <img src="https://img.shields.io/github/last-commit/oOo0oOo/leanclient" alt="last update" />
  </a>
  <a href="https://github.com/oOo0oOo/leanclient/blob/master/LICENSE">
    <img src="https://img.shields.io/github/license/oOo0oOo/leanclient.svg" alt="license" />
  </a>
</p>

<p align="center">
  <a href="#key-features">Key Features</a> •
  <a href="#quickstart">Quickstart</a> •
  <a href="#currently-in-beta">Currently in Beta</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#testing">Testing</a> •
  <a href="#license">License</a>
</p>

leanclient is a thin wrapper around the native Lean language server.
It enables interaction with a Lean language server instance running in a subprocess.

Check out the [documentation](https://leanclient.readthedocs.io) for more information.


## Key Features

- **Interact**: Query and change lean files via the [LSP](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)
- **Thin wrapper**: Directly expose the [Lean Language Server](https://github.com/leanprover/lean4/tree/master/src/Lean/Server).
- **Synchronous**: Requests block until a response is received.
- **Fast**: Typically more than 99% of time is spent waiting.
- **Parallel**: Easy batch processing of files using all your cores.


## Quickstart

The best way to get started is to check out this minimal example in Google Colab:

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/oOo0oOo/leanclient/blob/main/examples/getting_started_leanclient.ipynb)

Or try it locally:

1) Setup a new lean project or use an existing one. See the [colab notebook](examples/getting_started_leanclient.ipynb) for a basic Ubuntu setup.

2) Install the package:

```bash
pip install leanclient
```

3) In your python code:

```python
import leanclient as lc

# Start a new client, point it to your lean project root (where lakefile.toml is located).
PROJECT_PATH = "path/to/your/lean/project/root/"
client = lc.LeanLSPClient(PROJECT_PATH)

# Query a lean file in your project
file_path = "MyProject/Basic.lean"
result = client.get_goal(file_path, line=1, character=2)
print(result)

# Use a SingleFileClient for simplified interaction with a single file.
sfc = client.create_file_client(file_path)
result = sfc.get_term_goal(line=1, character=2)
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
```


## Currently in Beta

- The API is almost stable.
- There are missing features.
- Needs more testing with different setups.
- Any feedback is appreciated!


### Next Features

- Documentation: Real examples


### Potential Features

- Virtual files (no actual file on disk), only in-memory in lsp and client
- Use document versions to handle evolving file states
- Automatic lean env setup for non Debian-based systems
- Parallel implementation (multiple requests in-flight) like [multilspy](https://github.com/microsoft/multilspy/)
- Allow interaction before `waitForDiagnostics` returns


### Missing LSP Methods

Might be implemented in the future:
- `$/lean/rpc/connect`, `$/lean/rpc/call`, `$/lean/rpc/release`, `$/lean/rpc/keepAlive`
- `workspace/symbol`, `workspace/didChangeWatchedFiles`, `workspace/applyEdit`, ...
- `textDocument/prepareRename`, `textDocument/rename`
- `$/lean/ileanInfoUpdate`, `$/lean/ileanInfoFinal`, `$/lean/importClosure`, `$/lean/staleDependency`


## Documentation

Read the documentation at [leanclient.readthedocs.io](https://leanclient.readthedocs.io).

Run ``make docs`` to build the documentation locally.


## Testing

```bash
# python3 -m venv venv  # Or similar: Create environment
make install            # Installs python package and dev dependencies
make test               # Run all tests, also installs fresh lean env if not found
make test-profile       # Run all tests with cProfile
```


## License

MIT

Citing this repository is highly appreciated but not required by the license.