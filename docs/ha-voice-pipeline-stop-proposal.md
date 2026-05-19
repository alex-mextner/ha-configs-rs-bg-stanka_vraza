# HA Voice Pipeline Stop Control — Patch Proposal

## Summary
Add `assist_satellite.stop_pipeline` service to cancel running voice pipeline from UI/automations.

## Problem
Currently there's no way to stop a running voice pipeline from Home Assistant UI. If wake word fires falsely or user wants to abort TTS response, they have no control.

## Solution
Add entity service `stop_pipeline` gated by `AssistSatelliteEntityFeature.STOP_PIPELINE` feature flag.

## Architecture
- `assist_satellite` entity already tracks pipeline stage via state (`IDLE` → `LISTENING` → `PROCESSING` → `RESPONDING`)
- `AssistSatelliteEntity._cancel_running_pipeline()` already exists and handles task cleanup
- New service simply exposes this capability to users

## Changes

### 1. `homeassistant/components/assist_satellite/const.py`
```python
class AssistSatelliteEntityFeature(IntFlag):
    ANNOUNCE = 1
    START_CONVERSATION = 2
    STOP_PIPELINE = 4  # NEW
```

### 2. `homeassistant/components/assist_satellite/entity.py`
Add public method:
```python
async def async_stop_pipeline(self) -> None:
    """Stop the currently running pipeline on the satellite."""
    await self._cancel_running_pipeline()
```

### 3. `homeassistant/components/assist_satellite/__init__.py`
Register service:
```python
component.async_register_entity_service(
    "stop_pipeline",
    cv.make_entity_service_schema({}),
    "async_stop_pipeline",
    [AssistSatelliteEntityFeature.STOP_PIPELINE],
)
```

### 4. `homeassistant/components/assist_satellite/services.yaml`
```yaml
stop_pipeline:
  target:
    entity:
      domain: assist_satellite
      supported_features:
        - assist_satellite.AssistSatelliteEntityFeature.STOP_PIPELINE
  fields: {}
```

### 5. `homeassistant/components/assist_satellite/strings.json`
```json
"stop_pipeline": {
  "name": "Stop pipeline",
  "description": "Stops the currently running voice assistant pipeline on the satellite."
}
```

### 6. Test file: `tests/components/assist_satellite/test_entity.py`
Add test verifying service cancels active pipeline task.

## Why this approach?
- **Minimal**: ~40 lines across 7 files
- **Safe**: No changes to `PipelineRun` internals
- **Backward compatible**: Existing integrations unaffected (feature flag opt-in)
- **Follows HA patterns**: Same pattern as `announce` and `start_conversation` services

## Future extensions
- Per-stage abort flags (`abort_stt`, `abort_intent`, `abort_tts`) if needed later
- `button` entity for native UI button without services panel
- Domain-level `assist_pipeline.stop_run` for non-satellite pipelines

## Pull request checklist
- [ ] Target branch: `dev`
- [ ] Ruff formatting applied
- [ ] Type hints complete
- [ ] Tests pass
- [ ] No breaking changes
- [ ] Documentation updated
- [ ] Translations added
