# anysite-cli

Agent-first CLI for the Anysite API: Typer with Rich, sources in `src/anysite/`. One `anysite api <endpoint> key=value`
command serves every endpoint; `dataset`, `llm` and `db` are optional subsystems (extras `data`, `llm`, `clickhouse`).
Modules, subsystems, the agent protocol and the full command catalogue: skill `repo-map`.

## Commands

```bash
pip install -e ".[dev]"            # extras: ".[dev,data]", ".[dev,clickhouse]"
pytest                             # one test: pytest tests/test_cli/test_main.py::test_version
pytest --cov=anysite --cov-report=term-missing
ruff check src/                    # --fix; ruff format src/
mypy src/
anysite --help
anysite dataset guide
```

## Facts every change needs

- All Anysite API endpoints are POST with a JSON body; auth is the `access-token` header.
- Config: `~/.anysite/config.yaml`. Priority: CLI > ENV > config file > defaults.
- A non-TTY stdout gets the JSON envelope; every exception has an `error_code`, `exit_code` and `retryable`, every command next-step hints (`repo-map` → `subsystems.md` § Agent Protocol).
- Tests mirror `src/anysite/` under `tests/`.

## Changelog

**Every commit that adds features, fixes bugs or changes behaviour updates `src/anysite/changelog.py`**: agents read the changelog to discover new capabilities after an upgrade.

- Add a `Change(category=..., summary=...)` to the current version's `ChangeEntry` in `CHANGELOG`; a version bump starts a new `ChangeEntry` at the top.
- Categories: `added`, `changed`, `fixed`, `removed`.
- `summary` is one line (agents parse it); `detail` for significant features, `example` for YAML or command snippets.

## Release

1. Set the version in `pyproject.toml` and `src/anysite/__init__.py`, and add the new `ChangeEntry` with all changes since the last release.
2. Build and publish:
   ```bash
   rm -rf dist/ && python -m build
   TWINE_USERNAME=__token__ TWINE_PASSWORD='<pypi-token>' python -m twine upload dist/*
   ```
3. Commit those three files and push to `main`.
