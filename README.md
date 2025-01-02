# leanclient

Python client to interact with the Lean theorem prover language server.

## WIP!

Not tasty for consumption yet.

### Expect Changes

- Broad architecture, API and config changes
- Proper documentation
- Refactor environment setup, now only runs on Debian-based systems
- Publishing on pipy -> Installation via pip

### Planned Features

- Incremental file sync, currently only full files can be synced
- Capture file diagnostics on load
- Handle lake errors on requests, currently they are only printed in a separate thread

## Use

```bash
make install        # Installs python package and dev dependencies
make test           # Run all tests, also installs fresh lake env if not found
```

## License

MIT

Citing this repository is highly appreciated but not required by the license.