# Contributing

Contributions are welcome, especially documentation fixes, bug reports, tests, and small gameplay improvements.

For local development:

```bash
uv sync --locked --all-extras --dev
cp llmfight.ini.example llmfight.ini
uv run ruff format --check .
uv run ruff check .
uv run mypy src/llm_fight
uv run pytest -q
uv run pre-commit run --all-files
```

On PowerShell, copy the config with:

```powershell
Copy-Item llmfight.ini.example llmfight.ini
```

Please keep changes focused, add or update tests for behavior changes, and update `README.md` or `llmfight.ini.example` when commands or config change. Open an issue before large architecture or combat-system changes.

Do not commit API keys, private model URLs, local `.ini` files, transcripts containing private data, `.venv`, build artifacts, coverage files, or caches.
