# ruff: noqa: S101
"""Reading and writing notes over the websocket API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from custom_components.entity_note.const import (
    DOMAIN,
    MAX_NOTE_LENGTH,
    MIRROR_STORAGE_KEY,
    PRIVATE_STORAGE_KEY,
)

from .conftest import registry_entry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.typing import MockHAClientWebSocket

    from .conftest import SetupIntegration

PUBLIC = (
    "Hidden on purpose: takes over the TV screen.\nUse only when the Chromecast is off."
)
PRIVATE = "Router admin page: ask Lena 🙂"


async def _call(client: MockHAClientWebSocket, **message: Any) -> dict[str, Any]:
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def test_public_and_private_roundtrip(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    kitchen: er.RegistryEntry,
    hass_ws_client,
    hass_storage,
) -> None:
    """Public notes go to the registry options, private ones only to our store."""
    await setup_integration()
    client = await hass_ws_client(hass)

    reply = await _call(
        client,
        type=f"{DOMAIN}/update",
        entity_id="light.kitchen",
        public=f"  {PUBLIC}\r\n",
        private=PRIVATE,
    )
    assert reply["success"], reply
    assert reply["result"] == {
        "entity_id": "light.kitchen",
        "registry_id": kitchen.id,
        "public": PUBLIC,
        "private": PRIVATE,
    }

    entry = registry_entry(hass, "light.kitchen")
    assert entry.options[DOMAIN] == {"note": PUBLIC}
    # The private text is nowhere in the registry entry.
    assert PRIVATE not in json.dumps(entry.as_partial_dict, default=str)
    assert PRIVATE not in json.dumps(entry.extended_dict, default=str)

    assert (
        hass_storage[PRIVATE_STORAGE_KEY]["data"]["notes"][kitchen.id]["note"]
        == PRIVATE
    )
    mirror = hass_storage[MIRROR_STORAGE_KEY]["data"]["notes"][kitchen.id]
    assert mirror["public"] == PUBLIC
    assert mirror["private"] == PRIVATE

    reply = await _call(client, type=f"{DOMAIN}/get", entity_id="light.kitchen")
    assert reply["result"]["public"] == PUBLIC
    assert reply["result"]["private"] == PRIVATE

    reply = await _call(client, type=f"{DOMAIN}/list")
    assert reply["result"]["notes"] == [
        {
            "registry_id": kitchen.id,
            "entity_id": "light.kitchen",
            "state": "active",
            "public": PUBLIC,
            "private": PRIVATE,
            "updated_at": mirror["updated_at"],
        }
    ]


@pytest.mark.usefixtures("kitchen")
async def test_update_one_kind_keeps_the_other(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_ws_client,
) -> None:
    """Writing only the private note leaves the public one as it is."""
    await setup_integration()
    client = await hass_ws_client(hass)
    await _call(
        client, type=f"{DOMAIN}/update", entity_id="light.kitchen", public=PUBLIC
    )
    reply = await _call(
        client, type=f"{DOMAIN}/update", entity_id="light.kitchen", private=PRIVATE
    )
    assert reply["result"]["public"] == PUBLIC
    assert reply["result"]["private"] == PRIVATE


@pytest.mark.parametrize("empty", ["", "   \n  ", None])
@pytest.mark.usefixtures("kitchen")
async def test_empty_text_deletes(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_ws_client,
    hass_storage,
    empty: str | None,
) -> None:
    """Empty text or null removes the note, the namespace and the safety copy."""
    await setup_integration()
    client = await hass_ws_client(hass)
    await _call(
        client,
        type=f"{DOMAIN}/update",
        entity_id="light.kitchen",
        public=PUBLIC,
        private=PRIVATE,
    )
    reply = await _call(
        client,
        type=f"{DOMAIN}/update",
        entity_id="light.kitchen",
        public=empty,
        private=empty,
    )
    assert reply["result"]["public"] is None
    assert reply["result"]["private"] is None
    assert DOMAIN not in registry_entry(hass, "light.kitchen").options
    assert hass_storage[PRIVATE_STORAGE_KEY]["data"]["notes"] == {}
    assert hass_storage[MIRROR_STORAGE_KEY]["data"]["notes"] == {}


@pytest.mark.usefixtures("kitchen")
async def test_cyrillic_emoji_and_long_words_are_kept_as_is(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_ws_client,
) -> None:
    """Plain text, stored exactly (apart from outer whitespace)."""
    await setup_integration()
    client = await hass_ws_client(hass)
    cyrillic = "Не трогать 🔥\n"  # noqa: RUF001 - Cyrillic text on purpose
    text = cyrillic + "https://example.com/" + "a" * 300 + "\n\n**not markdown**"
    reply = await _call(
        client, type=f"{DOMAIN}/update", entity_id="light.kitchen", public=text
    )
    assert reply["result"]["public"] == text


@pytest.mark.usefixtures("kitchen")
async def test_too_long_is_refused(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_ws_client,
) -> None:
    """A pasted log does not end up in every registry list response."""
    await setup_integration()
    client = await hass_ws_client(hass)
    reply = await _call(
        client,
        type=f"{DOMAIN}/update",
        entity_id="light.kitchen",
        public="x" * (MAX_NOTE_LENGTH + 1),
    )
    assert not reply["success"]
    assert reply["error"]["code"] == "note_too_long"
    assert DOMAIN not in registry_entry(hass, "light.kitchen").options


async def test_entity_without_unique_id(
    hass: HomeAssistant, setup_integration: SetupIntegration, hass_ws_client
) -> None:
    """Entities outside the registry have no notes, like they have no UI name."""
    await setup_integration()
    hass.states.async_set("sensor.yaml_only", "1")
    client = await hass_ws_client(hass)
    for message in (
        {"type": f"{DOMAIN}/get", "entity_id": "sensor.yaml_only"},
        {"type": f"{DOMAIN}/update", "entity_id": "sensor.yaml_only", "public": "x"},
    ):
        reply = await _call(client, **message)
        assert reply["error"]["code"] == "not_found"


async def test_commands_are_admin_only(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    kitchen: er.RegistryEntry,
    hass_ws_client,
    hass_read_only_access_token: str,
) -> None:
    """A non-admin can use none of the commands, so private notes stay hidden."""
    await setup_integration()
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for message in (
        {"type": f"{DOMAIN}/get", "entity_id": "light.kitchen"},
        {"type": f"{DOMAIN}/list"},
        {"type": f"{DOMAIN}/update", "entity_id": "light.kitchen", "public": "x"},
        {"type": f"{DOMAIN}/update", "entity_id": "light.kitchen", "private": "x"},
        {"type": f"{DOMAIN}/forget", "registry_id": kitchen.id},
        {"type": f"{DOMAIN}/subscribe"},
        {"type": f"{DOMAIN}/frontend_report", "hooks": {"more_info": False}},
    ):
        reply = await _call(client, **message)
        assert not reply["success"], message
        assert reply["error"]["code"] == "unauthorized", message
    assert DOMAIN not in registry_entry(hass, "light.kitchen").options


@pytest.mark.usefixtures("kitchen")
async def test_non_admin_reads_public_note_only(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_ws_client,
    hass_read_only_access_token: str,
) -> None:
    """Non-admins see the public note through the stock registry API, never the private one."""
    await setup_integration()
    admin = await hass_ws_client(hass)
    await _call(
        admin,
        type=f"{DOMAIN}/update",
        entity_id="light.kitchen",
        public=PUBLIC,
        private=PRIVATE,
    )
    user = await hass_ws_client(hass, hass_read_only_access_token)
    for message in (
        {"type": "config/entity_registry/get", "entity_id": "light.kitchen"},
        {"type": "config/entity_registry/list"},
        {"type": "config/entity_registry/list_for_display"},
        {"type": "get_states"},
    ):
        reply = await _call(user, **message)
        assert reply["success"], message
        assert PRIVATE not in json.dumps(reply["result"], ensure_ascii=False), message
    reply = await _call(
        user, type="config/entity_registry/get", entity_id="light.kitchen"
    )
    assert reply["result"]["options"][DOMAIN]["note"] == PUBLIC


@pytest.mark.usefixtures("kitchen")
async def test_subscribe_sends_changes(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_ws_client,
) -> None:
    """Open UIs hear about every change and reload."""
    await setup_integration()
    listener = await hass_ws_client(hass)
    reply = await _call(listener, type=f"{DOMAIN}/subscribe")
    assert reply["success"]

    writer = await hass_ws_client(hass)
    await _call(writer, type=f"{DOMAIN}/update", entity_id="light.kitchen", private="x")
    event = await listener.receive_json()
    assert event["type"] == "event"
    assert event["id"] == reply["id"]


@pytest.mark.usefixtures("kitchen")
async def test_not_loaded(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_ws_client,
) -> None:
    """After unloading, the commands say so instead of failing."""
    entry = await setup_integration()
    await hass.config_entries.async_unload(entry.entry_id)
    client = await hass_ws_client(hass)
    reply = await _call(client, type=f"{DOMAIN}/list")
    assert reply["error"]["code"] == "not_loaded"


@pytest.mark.usefixtures("kitchen")
async def test_stock_registry_update_is_mirrored(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_ws_client,
) -> None:
    """A note written with config/entity_registry/update is kept in the safety copy."""
    await setup_integration()
    client = await hass_ws_client(hass)
    reply = await _call(
        client,
        type="config/entity_registry/update",
        entity_id="light.kitchen",
        options_domain=DOMAIN,
        options={"note": PUBLIC},
    )
    assert reply["success"]
    await hass.async_block_till_done()
    reply = await _call(client, type=f"{DOMAIN}/get", entity_id="light.kitchen")
    assert reply["result"]["public"] == PUBLIC
    notes = (await _call(client, type=f"{DOMAIN}/list"))["result"]["notes"]
    assert [row["public"] for row in notes] == [PUBLIC]
