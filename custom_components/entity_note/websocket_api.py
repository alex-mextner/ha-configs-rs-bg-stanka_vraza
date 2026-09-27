"""
Websocket commands. All are admin-only: they are the only way to private notes.

Non-admins read public notes with the stock ``config/entity_registry/get``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import voluptuous as vol
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import UNDEFINED

from .const import DOMAIN
from .notes import EntityNotes, NoteError

type _Handler = Callable[
    [ActiveConnection, dict[str, Any], EntityNotes],
    Awaitable[None] | None,
]

NOTE_TEXT = vol.Any(None, str)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the commands."""
    for command in (
        ws_get,
        ws_list,
        ws_update,
        ws_forget,
        ws_subscribe,
        ws_frontend_report,
    ):
        async_register_command(hass, command)


def _loaded_notes(hass: HomeAssistant) -> EntityNotes | None:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


def _with_notes(
    handler: _Handler,
) -> Callable[[HomeAssistant, ActiveConnection, dict[str, Any]], Any]:
    """Pass the loaded notes to the handler; turn NoteError into an error reply."""

    @wraps(handler)
    async def _wrapper(
        hass: HomeAssistant,
        connection: ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        notes = _loaded_notes(hass)
        if notes is None:
            connection.send_error(
                msg["id"], "not_loaded", "The Entity notes integration is not loaded"
            )
            return
        try:
            result = handler(connection, msg, notes)
            if result is not None:
                await result
        except NoteError as err:
            connection.send_error(msg["id"], err.code, str(err))

    return _wrapper


@require_admin
@websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get", vol.Required("entity_id"): cv.entity_id}
)
@async_response
@_with_notes
def ws_get(
    connection: ActiveConnection,
    msg: dict[str, Any],
    notes: EntityNotes,
) -> None:
    """Return the public and the private note of an entity."""
    connection.send_result(msg["id"], notes.async_get(msg["entity_id"]))


@require_admin
@websocket_command({vol.Required("type"): f"{DOMAIN}/list"})
@async_response
@_with_notes
def ws_list(
    connection: ActiveConnection,
    msg: dict[str, Any],
    notes: EntityNotes,
) -> None:
    """Return every note, including those of deleted entities."""
    connection.send_result(msg["id"], {"notes": notes.async_list()})


@require_admin
@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update",
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("public"): NOTE_TEXT,
        vol.Optional("private"): NOTE_TEXT,
    }
)
@async_response
@_with_notes
async def ws_update(
    connection: ActiveConnection,
    msg: dict[str, Any],
    notes: EntityNotes,
) -> None:
    """Write the public and/or private note; empty text or null deletes it."""
    result = await notes.async_set(
        msg["entity_id"],
        public=msg.get("public", UNDEFINED),
        private=msg.get("private", UNDEFINED),
    )
    connection.send_result(msg["id"], result)


@require_admin
@websocket_command(
    {vol.Required("type"): f"{DOMAIN}/forget", vol.Required("registry_id"): str}
)
@async_response
@_with_notes
async def ws_forget(
    connection: ActiveConnection,
    msg: dict[str, Any],
    notes: EntityNotes,
) -> None:
    """Delete the notes kept for an entity that is gone from the registry."""
    await notes.async_forget(msg["registry_id"])
    connection.send_result(msg["id"])


@require_admin
@websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@async_response
@_with_notes
def ws_subscribe(
    connection: ActiveConnection,
    msg: dict[str, Any],
    notes: EntityNotes,
) -> None:
    """Send an event whenever a note changes (the UI then reloads the list)."""

    @callback
    def _changed() -> None:
        connection.send_message(event_message(msg["id"], {}))

    connection.subscriptions[msg["id"]] = notes.async_add_listener(_changed)
    connection.send_result(msg["id"])


@require_admin
@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/frontend_report",
        vol.Required("hooks"): {cv.string: cv.boolean},
        vol.Optional("detail", default=""): vol.All(str, vol.Length(max=500)),
    }
)
@async_response
@_with_notes
def ws_frontend_report(
    connection: ActiveConnection,
    msg: dict[str, Any],
    notes: EntityNotes,
) -> None:
    """Record which UI hooks attached in an admin's browser."""
    notes.async_frontend_report(None, msg["hooks"], msg["detail"])
    connection.send_result(msg["id"])
