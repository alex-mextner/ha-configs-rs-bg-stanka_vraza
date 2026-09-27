# ruff: noqa: S101
"""Notes never reach Assist/LLM prompts, state attributes or diagnostics."""

from __future__ import annotations

import json

from homeassistant.components.homeassistant.exposed_entities import (
    async_expose_entity,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component

from custom_components.entity_note.const import DOMAIN
from custom_components.entity_note.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import SetupIntegration, notes_of, registry_entry

PUBLIC = "PUBLIC-NOTE-TEXT Используйте Chromecast"
PRIVATE = "PRIVATE-NOTE-TEXT only admins"


async def test_notes_stay_out_of_the_assist_prompt(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The Assist API (prompt and live context tool) never carries note text."""
    for component in ("homeassistant", "intent", "llm"):
        assert await async_setup_component(hass, component, {})
    entry = er.async_get(hass).async_get_or_create(
        "switch", "test", "tv-uid", suggested_object_id="tv", original_name="TV"
    )
    hass.states.async_set("switch.tv", "on", {"friendly_name": "TV"})
    async_expose_entity(hass, "conversation", entry.entity_id, should_expose=True)

    config_entry = await setup_integration()
    await notes_of(config_entry).async_set("switch.tv", public=PUBLIC, private=PRIVATE)

    api = await llm.async_get_api(
        hass,
        llm.LLM_API_ASSIST,
        llm.LLMContext(
            platform="test",
            context=Context(),
            language="en",
            assistant="conversation",
            device_id=None,
        ),
    )
    assert "NOTE-TEXT" not in api.api_prompt
    live_context = await api.async_call_tool(
        llm.ToolInput(tool_name="homeassistant__GetLiveContext", tool_args={})
    )
    dumped = json.dumps(live_context, ensure_ascii=False, default=str)
    assert "TV" in dumped  # the entity is exposed and listed ...
    assert "NOTE-TEXT" not in dumped  # ... without its notes

    state = hass.states.get("switch.tv")
    assert state is not None
    assert "NOTE-TEXT" not in json.dumps(state.as_dict(), default=str)


async def test_diagnostics_have_no_note_text(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Diagnostics get shared in bug reports: counts and lengths only."""
    er.async_get(hass).async_get_or_create(
        "light", "test", "kitchen-uid", suggested_object_id="kitchen"
    )
    config_entry = await setup_integration()
    await notes_of(config_entry).async_set(
        "light.kitchen", public=PUBLIC, private=PRIVATE
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    dumped = json.dumps(diagnostics, ensure_ascii=False, default=str)
    assert "NOTE-TEXT" not in dumped
    assert diagnostics["counts"]["public"] == 1
    assert diagnostics["counts"]["private"] == 1
    assert diagnostics["notes"][0]["private_length"] == len(PRIVATE)
    assert DOMAIN in registry_entry(hass, "light.kitchen").options
