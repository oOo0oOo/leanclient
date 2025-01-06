# leanclient

leanclient is a thin wrapper around the native Lean language server.
It enables interaction with a Lean language server instance running in a subprocess.

Check out the [documentation](https://leanclient.readthedocs.io) for more information.


## Key Features

- **Interact**: Query and change lean files via the [LSP](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)
- **Thin wrapper**: Directly expose the [Lean Language Server](https://github.com/leanprover/lean4/tree/master/src/Lean/Server).
- **Synchronous**: Requests block until a response is received.
- **Fast**: Typically more than 99% of time is spent waiting.
- **Parallel**: Easy batch processing of files using all your cores.


## Currently in Beta

**Not compatible** with Lean 4.15.0 (stable) yet.

- The API is almost stable.
- There are missing features.
- Needs more testing with different setups.
- Any feedback is appreciated!


### Next Features

- Documentation: Tutorial & examples
- Publishing on pipy


### Potential Features

- Virtual files (no actual file on disk), only in-memory in lsp and client
- Use document versions to handle evolving file states
- Automatic lean env setup for non Debian-based systems
- Parallel implementation (multiple requests in-flight) like [multilspy](https://github.com/microsoft/multilspy/)
- Allow interaction before `waitForDiagnostics` returns


### Missing LSP Methods

Might be implemented in the future:
- `callHierarchy/incomingCalls`, `callHierarchy/outgoingCalls`, ...
- `$/lean/rpc/connect`, `$/lean/rpc/call`, `$/lean/rpc/release`, `$/lean/rpc/keepAlive`
- `workspace/symbol`, `workspace/didChangeWatchedFiles`, `workspace/applyEdit`, ...
- `textDocument/prepareRename`, `textDocument/rename`
- `$/lean/ileanInfoUpdate`, `$/lean/ileanInfoFinal`, `$/lean/importClosure`, `$/lean/staleDependency`


## Run Tests

```bash
# python3 -m venv venv  # Or similar: Create environment
make install            # Installs python package and dev dependencies
make test               # Run all tests, also installs fresh lean env if not found
make test-profile       # Run all tests with cProfile
```

## Documentation

Read the documentation at [leanclient.readthedocs.io](https://leanclient.readthedocs.io).

Run ``make docs`` to build the documentation locally.


## License

MIT

Citing this repository is highly appreciated but not required by the license.