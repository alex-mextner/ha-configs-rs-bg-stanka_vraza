# AGENTS.md — home-generative-agent

## Project summary
Home Assistant custom integration providing a generative agent. Core code lives in
`custom_components/home_generative_agent/`, tests in `tests/`.

## Repo layout
- `custom_components/home_generative_agent/` — integration code
- `tests/` — pytest suite
- `blueprints/` — HA blueprints used by the integration
- `scripts/` — helper scripts (notably `gen_manifest_requirements.py`)
- `requirements/` + `requirements_runtime_manifest.txt` — dependency management

## Integration module map
- `sentinel/` — anomaly detection engine, dynamic rules, proposals, suppression
- `snapshot/` — snapshot schema/builders/reducers used by Sentinel and explain flows
- `notify/` — mobile notification dispatch and action helpers
- `explain/` — prompt templates and LLM-backed explanation/discovery helpers

## Development environment
- Python: 3.14
- Virtualenv: `hga/` (managed by Makefile)
- Primary tools: `ruff` (format + lint), `pyright` (types), `pytest`

## Common commands (Makefile)
- `make venv` — create venv
- `make devdeps` — install dev deps
- `make testdeps` — install test deps
- `make runtimedeps` — regenerate + install runtime deps from manifest
- `make lint` — regenerate runtime deps + `ruff check` (non-mutating)
- `make format` — `ruff format`
- `make fix` — `ruff check --fix`
- `make test` — pytest (sets `PYTHONPATH` to repo root)
- `make typecheck` — `pyright`
- `make all` — devdeps + testdeps + runtimedeps + lint + test + check + typecheck

Note: `make lint` will fail if `requirements_runtime_manifest.txt` is out of date.

## Dependency workflow
Runtime dependencies are sourced from
`custom_components/home_generative_agent/manifest.json`.

- Don’t edit `requirements_runtime_manifest.txt` directly.
- After changing `manifest.json`, run `scripts/gen_manifest_requirements.py`
  (or `make runtimedeps`).

## Coding conventions
- Formatting/linting: `ruff format` + `ruff check`
- Type checking: `pyright` (standard mode)
- Prefer async I/O and Home Assistant patterns (`async_*` APIs,
  `async_add_executor_job` for blocking work).
- Update docs when behavior or config changes (README is the primary user doc).

## Testing
- Run `make test` for the full suite.
- Keep tests under `tests/` and mirror integration module structure where
  practical.

## Notes
- The integration is a Home Assistant service integration (`manifest.json`).
- Prefer the Makefile workflow for setup/tasks (`make devdeps`, `make testdeps`,
  `make runtimedeps`) over legacy helper scripts.

## Home Assistant Docker management
HA runs in Docker under `homeassistant-homeassistant-1`. All docker commands run as
current user (no `sudo`/`run0` needed).

**Reload automations/config:** `docker restart homeassistant-homeassistant-1`

**Access HA API:**
- Token stored in `~/.env` as `HA_TOKEN`
- Base URL: `http://localhost:8123/api`
- Use: `curl -H "Authorization: Bearer $HA_TOKEN" ...`

**Other useful commands:**
- `docker exec -it homeassistant-homeassistant-1 bash` — shell inside container
- `docker logs -f homeassistant-homeassistant-1` — view logs
- `docker ps` — list all containers

**Tip:** `touch ~/.env` (if needed) as current user — never use sudo for dotfiles in ~.

**Rule:** Prefer current user for all operations. Never use `sudo` or `run0` unless strictly required. If a file in `~` requires root access, fix its permissions instead of using elevated privileges.

## Critical rules — Home Assistant config safety

**NEVER** manually edit, delete, modify, or overwrite `.storage/` files (like `core.config_entries`,
`core.entity_registry`, `assist_pipeline.pipelines`, `lovelace_dashboards`, etc.).
These files are HA's internal runtime state and must only be modified through
Home Assistant APIs (REST API, Websocket API, services) or configuration files
(`configuration.yaml`, `automations.yaml`, etc.).

- Always prefer HA REST API, Websocket API, or service calls over manual file edits.
- Use `configuration.yaml`, `automations.yaml`, `scripts.yaml`, and other config files for persistent settings.
- If an operation requires touching `.storage/`, find the equivalent API endpoint or UI path first.
- Before any destructive operation on HA config:
  1. Always create a backup first
  2. Confirm with user before making changes
  3. Use the fail-safe scripts in `scripts/ha_fail_safe.sh` for entity registry fixes

**NEVER** delete, modify, or overwrite backups (e.g., `backups/`, `config_backup_*`, `*.tar` in repo root) without explicit user consent. Backups are the safety net for recovery.

If something breaks — restore from backup immediately.

## Git workflow

**Commit messages must be atomic** — one commit per logical change.
- Good: "fix TTS entity orphaned state" / "add health check cron"
- Bad: "fix multiple issues" / "updates"

**Always commit atomically as you work.** Do not wait for an explicit user request to commit. After each logical change (feature, fix, or config update), create a commit immediately. This keeps the history clean and makes rollbacks safe.

**NEVER commit secrets, credentials, or `.env` files.**
**NEVER commit changes to `.storage/` files directly.**

Use `git diff` to verify changes before committing.
