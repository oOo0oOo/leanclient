<h1 align="center">
  leanclient
</h1>

<h4 align="center">Interact with the lean4 language server in Python.</h4>

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

leanclient is a thin Python wrapper around the native Lean language server.
It enables interaction with a Lean language server instance running in a subprocess.

Check out the [documentation](https://leanclient.readthedocs.io) for more information.

## Key Features

- **Interact**: Query and change lean files via the [LSP](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/).
- **Thin wrapper**: Directly expose the [Lean Language Server](https://github.com/leanprover/lean4/tree/master/src/Lean/Server).
- **Synchronous**: Requests block until a response is received.
- **Fast**: Typically more than 95% of time is spent waiting.
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
file_path = "MyProject/Basic.lean")
result = client.get_goal(file_path, line=1, character=2)
print(result)

# Use a SingleFileClient for simplified interaction with a single file.
sfc = client.create_file_client(file_path)
result = sfc.get_term_goal(line=1, character=2)
print(result)

# Make a change to the document.
change = lc.DocumentContentChange(text="-- Adding a comment at the head of the file\n", start=[0, 0], end=[0, 0])
sfc.update_file(changes=[change])

# Check the document content as seen by the LSP (changes are not written to disk).
print(sfc.get_file_content())

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

### Implemented LSP Interactions

See the [documentation](https://leanclient.readthedocs.io) for more information on:

- Opening and closing files.
- Updating (adding/removing) code from an open file.
- Diagnostic information: Errors, warnings etc
- Goals and term goal.
- Hover information.
- Document symbols (theorems, definitions, etc).
- Semantic tokens, folding ranges, and document highlights.
- Locations of definitions and type definitions.
- Locations of declarations and references.
- Completions, completion item resolve.

### Missing LSP Interactions

- "Call hierarchy" and "code action" is currently not reliable.

Might be implemented in the future:

- `textDocument/codeAction`
- `workspace/symbol`, `workspace/didChangeWatchedFiles`, `workspace/applyEdit`, ...
- `textDocument/prepareRename`, `textDocument/rename`

Internal Lean methods:

- `$/lean/rpc/connect`, `$/lean/rpc/call`, `$/lean/rpc/release`, `$/lean/rpc/keepAlive`
- Interactive diagnostics
- `$/lean/staleDependency`

### Potential Features

- Choose between `lean --server` and `lake serve`
- Allow interaction before `waitForDiagnostics` returns.
- Parallel implementation (multiple requests in-flight) like [multilspy](https://github.com/microsoft/multilspy/)
- Automatic testing (lean env setup) for non Debian-based systems
- Use document versions to handle evolving file states

## Documentation

Read the documentation at [leanclient.readthedocs.io](https://leanclient.readthedocs.io).

Run ``make docs`` to build the documentation locally.

## Benchmarks

See [documentation](https://leanclient.readthedocs.io/en/latest/benchmarks.html) for more information.

## Testing

```bash
# python3 -m venv venv  # Or similar: Create environment
make install            # Installs python package and dev dependencies
make test               # Run all tests, also installs fresh lean env if not found
make test-profile       # Run all tests with cProfile
```

## Related Projects

### Lean LSP Clients

- [vscode-lean4](https://github.com/leanprover/vscode-lean4)
- [lean-client-js](https://github.com/leanprover/lean-client-js/)
- [lean-client-python](https://github.com/leanprover-community/lean-client-python)
- [communicating-with-lean](https://github.com/jasonrute/communicating-with-lean)

### Lean REPLs

- [LeanDojo](https://github.com/lean-dojo/LeanDojo)
- [PyPantograph](https://github.com/lenianiva/PyPantograph)
- [lean-repl-py](https://github.com/sorgfresser/lean-repl-py)
- [repl](https://github.com/leanprover-community/repl)
- [minictx-eval](https://github.com/cmu-l3/minictx-eval)
- [LeanREPL](https://github.com/arthurpaulino/LeanREPL)
- [LeanTool](https://github.com/GasStationManager/LeanTool)
- [itp-interface](https://github.com/trishullab/itp-interface)

## License & Citation

**MIT** licensed. See [LICENSE](LICENSE) for more information.

Citing this repository is highly appreciated but not required by the license.

```bibtex
@software{leanclient2025,
  author = {Oliver Dressler},
  title = {{leanclient: Python client to interact with the lean4 language server}},
  url = {https://github.com/oOo0oOo/leanclient},
  month = {1},
  year = {2025}
}
```
