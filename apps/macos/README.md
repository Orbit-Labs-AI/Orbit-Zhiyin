# Tandem Mac host

`Tandem.swift` owns the window, offline WKWebView, directory/save panels and the Python helper lifecycle. `build.py` packages the runtime and resources; `server_entry.py` is the frozen helper entry point.

Build from the repository root:

```sh
uv run python apps/macos/build.py
open .local/macos-build/Tandem.app
```

The default build is ad-hoc signed for local use. Configure `TANDEM_SIGN_IDENTITY` and `TANDEM_NOTARY_PROFILE` for Developer ID distribution. No developer certificate is bundled. The current target is arm64/macOS 15; this is not a Mac App Store sandbox target.

See [desktop integration](../../docs/backend/mac-app.md) for API, lifecycle, UI mapping, authorized real-data acceptance and known boundaries.
