# leanclient

Python client to interact with the Lean theorem prover language server.

## WIP!

Not tasty for consumption yet.

### Planned Features

- Broad architecture, API and config changes
- Proper documentation
- Publishing on pipy -> Installation via pip

### Potential Features

- Parallel implementation (multiple requests in-flight) like [multilspy](https://github.com/microsoft/multilspy/)
- Allow interaction before `waitForDiagnostics` returns
- Automatic lean env setup for non Debian-based systems

### Missing LSP Features

Might be implemented in the future:
- `workspace/symbol`, `workspace/didChangeWatchedFiles`, `workspace/applyEdit`, ...
- `callHierarchy/incomingCalls`, `callHierarchy/outgoingCalls`, ...
- `textDocument/prepareRename`, `textDocument/rename`

Not even sure if these methods are exposed via the Lean language server:
- `$/lean/rpc/connect`, `$/lean/rpc/call`, `$/lean/rpc/release`, `$/lean/rpc/keepAlive`
- `$/lean/ileanInfoUpdate`, `$/lean/ileanInfoFinal`, `$/lean/importClosure`, `$/lean/staleDependency`

## Features

- **Interact** with a Lean language server instance running in a subprocess.
- Automatically **sync files** (open/close) with the language server.
- **Incremental** file changes using `textDocument/didChange`.
- Receive file **diagnostics** upon changes.
- **Thin wrapper**: During (`make test-profile`) less than 1% of 38s is spent in this package.

## Use

```bash
# python3 -m venv venv  # Or similar: Create environment
make install            # Installs python package and dev dependencies
make test               # Run all tests, also installs fresh lean env if not found
make test-profile       # Run all tests with cProfile
```

## License

MIT

Citing this repository is highly appreciated but not required by the license.