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

## custom_components/ management

All third-party integrations are managed as **Git submodules** cloned into `submodules/`,
with **symlinks** from `custom_components/<domain>/` pointing to
`submodules/<repo>/custom_components/<domain>/`. This keeps the repo clean while
allowing HA to load integrations normally.

### Current submodules

| Submodule | Symlink | Repository | Pin |
|---|---|---|---|
| `submodules/dataplicity` | `custom_components/dataplicity` | `alex-mextner/Dataplicity` | branch `fix/dataplicity-modern-api` |
| `submodules/hacs` | `custom_components/hacs` | `hacs/integration` | tag `2.0.5` |
| `submodules/home-generative-agent` | `custom_components/home_generative_agent` | `goruck/home-generative-agent` | branch `main` |
| `submodules/hass-mcp-server` | `custom_components/mcp_server_http_transport` | `ganhammar/hass-mcp-server` | tag `v1.8.0` |
| `submodules/HA-WiFi-Sensor-Tracker` | `custom_components/wifi_sensor_tracker` | `5a2v0/HA-WiFi-Sensor-Tracker` | tag `2.2.5` |
| `submodules/xtend_tuya` | `custom_components/xtend_tuya` | `azerty9971/xtend_tuya` | tag `v4.4.7` |
| `submodules/YandexDialogs` | `custom_components/yandex_dialogs` | `AlexxIT/YandexDialogs` | tag `v1.3.2` |
| `submodules/yandex_smart_home` | `custom_components/yandex_smart_home` | `dext0r/yandex_smart_home` | tag `v1.1.2` |
| `submodules/YandexStation` | `custom_components/yandex_station` | `AlexxIT/YandexStation` | tag `v3.21.0` |

### Rules
- **Do not copy third-party code directly** into this repo. Always add it as a submodule.
- `dataplicity` is a **patched fork** — upstream fixes live in `fix/dataplicity-modern-api`.
  Never replace it with vanilla upstream without checking the patch delta.
- `home_generative_agent` is tracked on upstream `goruck/home-generative-agent`.
  If local patches are needed, either fork upstream or patch here and push to the fork.
- **HACS special case:** upstream `.gitignore` excludes `hacs_frontend`. After cloning,
  copy the `hacs_frontend` pip package into `submodules/hacs/custom_components/hacs/hacs_frontend/`
  and commit inside the submodule so HA can import it.
- To update a submodule: `cd submodules/<repo> && git fetch --tags && git checkout <new-tag>`.
  Then commit the submodule pointer change and symlink in the parent repo.
- When cloning this repo on a new machine, use `git clone --recurse-submodules` or run
  `git submodule update --init --recursive` afterwards.

### HACS version cache mismatch
When submodules are updated via `git` (not through the HACS UI), HACS still shows the old version in its `update.*` entities because it caches `installed_commit` and `version_installed` in `.storage/hacs.repositories`.

**Fix:** Update the cached values in `.storage/hacs.repositories` to match the current submodule HEAD and manifest version, then restart HA (or call `update.clear_skipped` if you previously skipped the stale notifications).

Example quick-fix (run from repo root after updating submodules):
```python
import json, subprocess

repo_map = {
    "goruck/home-generative-agent": ("submodules/home-generative-agent", "home_generative_agent"),
    "5a2v0/HA-WiFi-Sensor-Tracker": ("submodules/HA-WiFi-Sensor-Tracker", "wifi_sensor_tracker"),
    "azerty9971/xtend_tuya": ("submodules/xtend_tuya", "xtend_tuya"),
    "AlexxIT/Dataplicity": ("submodules/dataplicity", "dataplicity"),
    "dext0r/yandex_smart_home": ("submodules/yandex_smart_home", "yandex_smart_home"),
    "AlexxIT/YandexStation": ("submodules/YandexStation", "yandex_station"),
    "ganhammar/hass-mcp-server": ("submodules/hass-mcp-server", "mcp_server_http_transport"),
    "hacs/integration": ("submodules/hacs", "hacs"),
}

with open('.storage/hacs.repositories') as f:
    data = json.load(f)

for repo_key, repo_val in data['data'].items():
    full_name = repo_val.get('full_name')
    if full_name not in repo_map:
        continue
    submodule_path, domain = repo_map[full_name]
    head = subprocess.check_output(
        ['git', '-C', submodule_path, 'rev-parse', '--short', 'HEAD']
    ).decode().strip()
    with open(f"{submodule_path}/custom_components/{domain}/manifest.json") as mf:
        manifest = json.load(mf)
    version = manifest.get('version', '')
    repo_val['installed_commit'] = head
    repo_val['version_installed'] = str(version) if version else repo_val.get('last_version', '')

with open('.storage/hacs.repositories', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

Then restart HA: `docker restart homeassistant-homeassistant-1`.

**Note:** `.storage/hacs.data` and `.storage/hacs.repositories` are HA runtime state files. Always back them up (`cp .storage/hacs.repositories /tmp/hacs.repositories.backup.$(date +%Y%m%d_%H%M%S).json`) before editing.

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

**When restoring from backup, do not blindly overwrite files.** Always preserve changes made after the backup was taken. Use `git diff`, `tar --diff`, or manual review to merge new work with the restored state.

## Lessons learned — critical incident 2026-05-18

### What broke
An attempt to "clean up git history" caused a cascading failure:
1. `git clean -fdx` deleted HA runtime files (`.storage/`, `home-assistant_v2.db`, `automations.yaml`, `scripts.yaml`, `scenes.yaml`, `.cloud/`, `.cache/`, `.HA_VERSION`, logs, Zigbee DB).
2. `git checkout --orphan main` erased 23 commits of HA config history.
3. Submodules were placed directly in `custom_components/<domain>/` — but upstream repos nest the actual integration code inside `custom_components/<domain>/custom_components/<domain>/`, so all integrations silently failed to load.
4. HACS broke because `hacs_frontend` (pip package) was missing from the submodule.
5. Dataplicity credentials were overwritten with old values from an older backup.

### Recovery
- Restored `.storage/`, DB, configs from `ha-config-20260518_030001.tar.gz` (cron backup).
- Replaced dataplicity credentials from `/tmp/pre_bm/.storage/core.config_entries`.
- Moved submodules to `submodules/` with symlinks into `custom_components/`.
- Copied `hacs_frontend` pip package into the HACS submodule and committed inside it.

### Rules enforced from now on
- **NEVER run `git clean` in this repo.** It unconditionally destroys runtime files.
- **NEVER run `git checkout --orphan`, `git rebase`, `git reset --hard`, or any destructive history rewrite on `main`.** If orphan history is truly needed, create a new branch and keep `main` intact.
- **NEVER delete backups.** Ever. Even if they seem old or redundant. Disk space is cheap; lost configuration is expensive. This includes `backups/`, `*.tar`, `.storage.backup*`, `/tmp/ha-backup-*`, `/tmp/pre_bm/`, and any other backup artifacts.
- **Before any destructive operation:** `cp -r /home/ultra/homeassistant /tmp/ha-backup-$(date +%Y%m%d_%H%M%S)`.
- **When restoring from backup, do not blindly overwrite files.** Always preserve changes made after the backup was taken. Use `git diff`, `tar --diff`, or manual review to merge new work with the restored state.
- **For root-owned files** (e.g. Docker-created `.pyc` or `.storage` entries), use `docker run --rm -v <path>:/target alpine sh -c "rm -rf /target/<file>"` instead of `sudo`.

## Git workflow

**Commit messages must be atomic** — one commit per logical change.
- Good: "fix TTS entity orphaned state" / "add health check cron"
- Bad: "fix multiple issues" / "updates"

**Always commit atomically as you work.** Do not wait for an explicit user request to commit. After each logical change (feature, fix, or config update), create a commit immediately. This keeps the history clean and makes rollbacks safe.

**NEVER commit secrets, credentials, or `.env` files.**
**NEVER commit changes to `.storage/` files directly.**

Use `git diff` to verify changes before committing.

# HA Fail-Safe System

## Problem
Editing `.storage/core.entity_registry` directly caused HA to become unavailable. Root causes:
1. Orphaned TTS entity `tts.j_a_r_v_i_s_j_a_r_v_i_s` without `config_entry_id` caused service registration failure
2. Direct file editing bypasses HA's internal validation
3. No monitoring to detect/fix such issues automatically

## Solution: Fail-Safe System

### Scripts

#### 1. ha_fail_safe.sh
Main fail-safe management script.
```bash
./scripts/ha_fail_safe.sh [check|fix-orphaned|restart|status]
```

Examples:
```bash
# Check HA availability
./scripts/ha_fail_safe.sh check

# Check full status including TTS
./scripts/ha_fail_safe.sh status

# Auto-fix orphaned entities
./scripts/ha_fail_safe.sh fix-orphaned

# Safe restart
./scripts/ha_fail_safe.sh restart
```

#### 2. ha_health_monitor.py
Advanced monitoring with API integration.
```bash
python3 scripts/ha_health_monitor.py
```

### Cron Jobs (already configured)
```
0 3 * * * /home/ultra/backup-ha.sh >/dev/null 2>&1  # Backup
0 8,20 * * * /home/ultra/homeassistant/scripts/ha_fail_safe.sh check >> /tmp/ha_check.log 2>&1  # Health check
```

### How It Works

1. **Detection**: Every 12 hours, `ha_fail_safe.sh check` verifies HA accessibility
2. **Status Report**: `ha_fail_safe.sh status` shows:
   - HA accessibility status
   - Orphaned entities count
   - TTS pipeline configuration validity
   - Container uptime

3. **Auto-Fix**: `fix-orphaned` automatically:
   - Backs up entity registry before changes
   - Removes orphaned TTS entities (those with `orphaned_timestamp` and no `config_entry_id`)
   - Validates pipeline configuration

4. **Safe Restart**: `restart` ensures HA comes back online before declaring success

### TTS Configuration for J.A.R.V.I.S

Pipeline "Милош" uses:
- TTS Engine: `tts.j_a_r_v_i_s_j_a_r_v_i_s`
- Language: ru
- Via Fish Audio integration

Valid TTS entity must have:
- `config_entry_id`: linked to Fish Audio config entry
- `orphaned_timestamp`: null (not orphaned)

### Emergency Recovery

If HA becomes unavailable after entity registry edit:

1. Check status: `/home/ultra/homeassistant/scripts/ha_fail_safe.sh status`
2. If orphaned entities found: `/home/ultra/homeassistant/scripts/ha_fail_safe.sh fix-orphaned`
3. If still down: `/home/ultra/homeassistant/scripts/ha_fail_safe.sh restart`
4. Check logs: `tail -f /tmp/ha_fail_safe/*.log`

### Backup Location
Backups are stored at: `/tmp/ha_fail_safe/entity_registry.backup.*`

### Files Modified
- `.storage/core.entity_registry` - Entity registry (auto-backed up before changes)
- `automations.yaml` - Health check automations
- `scripts/ha_fail_safe.sh` - Main management script
- `scripts/ha_health_monitor.py` - Advanced Python monitor

## Prevention
Never edit `.storage/core.entity_registry` directly. Always use `ha_fail_safe.sh fix-orphaned` or `ha_health_monitor.py` which:
1. Create backups automatically
2. Validate changes before writing
3. Trigger HA restart if needed
