# leanclient

Python client to interact with the Lean theorem prover language server.

## WIP!

Ready for use soon.

### Planned Features

- Smaller architecture, API and config changes
- Proper documentation & examples
- Publishing on pipy -> Installation via pip

### Potential Features

- Virtual files (no actual file on disk), only in-memory in lsp and client
- Simple pool of parallel clients for faster scraping
- Use document versions to handle evolving file states
- Automatic lean env setup for non Debian-based systems
- Parallel implementation (multiple requests in-flight) like [multilspy](https://github.com/microsoft/multilspy/)
- Allow interaction before `waitForDiagnostics` returns

### Missing LSP Features

Might be implemented in the future:
- `callHierarchy/incomingCalls`, `callHierarchy/outgoingCalls`, ...
- `$/lean/rpc/connect`, `$/lean/rpc/call`, `$/lean/rpc/release`, `$/lean/rpc/keepAlive`
- `workspace/symbol`, `workspace/didChangeWatchedFiles`, `workspace/applyEdit`, ...
- `textDocument/prepareRename`, `textDocument/rename`
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