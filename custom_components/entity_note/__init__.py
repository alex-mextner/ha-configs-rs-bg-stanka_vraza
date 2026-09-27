"""
Notes on entities: why an entity is set up the way it is.

Public notes live in the entity registry entry, private ones (admins only) in this
integration's own store. Only the UI reads them: they never reach Assist, LLM
integrations or state attributes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir

from . import websocket_api
from .const import DOMAIN, ISSUE_FRONTEND_HOOKS, ISSUE_MISSING_NOTES
from .frontend import async_register_frontend
from .notes import EntityNotes

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

type EntityNoteConfigEntry = ConfigEntry[EntityNotes]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
    """Register the websocket commands (they answer only while an entry is loaded)."""
    websocket_api.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EntityNoteConfigEntry) -> bool:
    """Load the notes, follow the registry and add the UI."""
    notes = EntityNotes(hass)
    await notes.async_load()
    entry.runtime_data = notes
    entry.async_on_unload(notes.async_start())
    entry.async_on_unload(await async_register_frontend(hass, notes))
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: EntityNoteConfigEntry,  # noqa: ARG001
) -> bool:
    """Remove the UI. The notes stay in the registry and in .storage."""
    for issue_id in (ISSUE_MISSING_NOTES, ISSUE_FRONTEND_HOOKS):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    return True
