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
