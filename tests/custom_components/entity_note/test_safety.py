# ruff: noqa: S101
"""Notes survive renames, delete/re-add and restarts; lost notes are offered back."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.entity_note.const import (
    DOMAIN,
    ISSUE_FRONTEND_HOOKS,
    ISSUE_MISSING_NOTES,
    MIRROR_STORAGE_KEY,
    PRIVATE_STORAGE_KEY,
)
from custom_components.entity_note.notes import EntityNotes

from .conftest import SetupIntegration, notes_of, registry_entry, repair_issue, storage

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

PUBLIC = "Use only when the Chromecast is off."
PRIVATE = "Admin detail."


def _mirror_record(
    entry: er.RegistryEntry, public: str | None = PUBLIC, private: str | None = PRIVATE
) -> dict[str, Any]:
    return {
        "entity_id": entry.entity_id,
        "platform": entry.platform,
        "unique_id": entry.unique_id,
        "public": public,
        "private": private,
        "updated_at": "2026-09-26T12:00:00+00:00",
    }


def _private_record(entry: er.RegistryEntry, note: str = PRIVATE) -> dict[str, Any]:
    return {
        "note": note,
        "entity_id": entry.entity_id,
        "updated_at": "2026-09-26T12:00:00+00:00",
    }


async def _fix(hass_client, next_step: str) -> dict:
    """Run the Repairs fix flow of the missing-notes issue."""
    client = await hass_client()
    response = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": DOMAIN, "issue_id": ISSUE_MISSING_NOTES},
    )
    assert response.status == HTTPStatus.OK
    flow = await response.json()
    assert flow["type"] == "menu"
    assert flow["menu_options"] == ["restore", "discard"]
    response = await client.post(
        f"/api/repairs/issues/fix/{flow['flow_id']}", json={"next_step_id": next_step}
    )
    result = await response.json()
    if result["type"] == "form":  # discard asks once more
        response = await client.post(
            f"/api/repairs/issues/fix/{flow['flow_id']}", json={}
        )
        result = await response.json()
    assert result["type"] == "create_entry", result
    return result


@pytest.mark.usefixtures("kitchen")
async def test_rename_keeps_both_notes(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The notes follow the registry entry, not the entity_id."""
    entry = await setup_integration()
    notes = notes_of(entry)
    await notes.async_set("light.kitchen", public=PUBLIC, private=PRIVATE)

    er.async_get(hass).async_update_entity(
        "light.kitchen", new_entity_id="light.kukhnia", name="Кухня"
    )
    await hass.async_block_till_done()

    assert notes.async_get("light.kukhnia")["public"] == PUBLIC
    assert notes.async_get("light.kukhnia")["private"] == PRIVATE
    assert [row["entity_id"] for row in notes.async_list()] == ["light.kukhnia"]
    assert not ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MISSING_NOTES)


async def test_delete_and_readd_keeps_both_notes(
    hass: HomeAssistant, setup_integration: SetupIntegration, kitchen: er.RegistryEntry
) -> None:
    """A deleted entity keeps its notes and gets them back when it returns."""
    entry = await setup_integration()
    notes = notes_of(entry)
    await notes.async_set("light.kitchen", public=PUBLIC, private=PRIVATE)
    registry = er.async_get(hass)

    registry.async_remove("light.kitchen")
    await hass.async_block_till_done()
    [row] = notes.async_list()
    assert row["state"] == "deleted"
    assert (row["public"], row["private"]) == (PUBLIC, PRIVATE)

    readded = registry.async_get_or_create(
        "light", "test", "kitchen-uid", suggested_object_id="kitchen"
    )
    await hass.async_block_till_done()
    assert readded.id == kitchen.id
    assert notes.async_get("light.kitchen") == {
        "entity_id": "light.kitchen",
        "registry_id": kitchen.id,
        "public": PUBLIC,
        "private": PRIVATE,
    }
    assert not ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MISSING_NOTES)


async def test_notes_survive_a_restart(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    kitchen: er.RegistryEntry,
    hass_storage,
) -> None:
    """Both stores are written at once and read back by a fresh instance."""
    entry = await setup_integration()
    await notes_of(entry).async_set("light.kitchen", public=PUBLIC, private=PRIVATE)
    await hass.config_entries.async_unload(entry.entry_id)

    fresh = EntityNotes(hass)
    await fresh.async_load()
    fresh.async_check()
    assert fresh.async_get("light.kitchen")["private"] == PRIVATE
    assert fresh.missing == {}
    assert (
        hass_storage[PRIVATE_STORAGE_KEY]["data"]["notes"][kitchen.id]["note"]
        == PRIVATE
    )


async def test_first_start_adopts_existing_notes(
    hass: HomeAssistant,
    kitchen: er.RegistryEntry,
    setup_integration: SetupIntegration,
    hass_storage,
) -> None:
    """Without a safety copy, the copy is built from the registry and the store."""
    er.async_get(hass).async_update_entity_options(
        "light.kitchen", DOMAIN, {"note": PUBLIC}
    )
    hass_storage[PRIVATE_STORAGE_KEY] = storage(
        PRIVATE_STORAGE_KEY, {kitchen.id: _private_record(kitchen)}
    )
    await setup_integration()
    mirror = hass_storage[MIRROR_STORAGE_KEY]["data"]["notes"]
    assert mirror[kitchen.id]["public"] == PUBLIC
    assert mirror[kitchen.id]["private"] == PRIVATE


async def test_lost_public_note_at_startup_is_restored(
    hass: HomeAssistant,
    kitchen: er.RegistryEntry,
    setup_integration: SetupIntegration,
    hass_storage,
    hass_client,
) -> None:
    """The registry lost the note (e.g. restored from an old file): Repairs puts it back."""
    hass_storage[MIRROR_STORAGE_KEY] = storage(
        MIRROR_STORAGE_KEY, {kitchen.id: _mirror_record(kitchen, private=None)}
    )
    await setup_integration()

    issue = repair_issue(hass, ISSUE_MISSING_NOTES)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.is_fixable
    assert (issue.translation_placeholders or {})["count"] == "1"
    assert "light.kitchen" in (issue.translation_placeholders or {})["entities"]

    await _fix(hass_client, "restore")
    await hass.async_block_till_done()
    assert registry_entry(hass, "light.kitchen").options[DOMAIN] == {"note": PUBLIC}
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MISSING_NOTES) is None


async def test_lost_private_store_is_restored(
    hass: HomeAssistant,
    kitchen: er.RegistryEntry,
    setup_integration: SetupIntegration,
    hass_storage,
    hass_client,
) -> None:
    """The private store was lost or damaged: the safety copy brings the notes back."""
    hass_storage[MIRROR_STORAGE_KEY] = storage(
        MIRROR_STORAGE_KEY, {kitchen.id: _mirror_record(kitchen, public=None)}
    )
    entry = await setup_integration()
    issue = repair_issue(hass, ISSUE_MISSING_NOTES)
    assert "private" in (issue.translation_placeholders or {})["entities"]

    await _fix(hass_client, "restore")
    assert notes_of(entry).async_get("light.kitchen")["private"] == PRIVATE
    assert (
        hass_storage[PRIVATE_STORAGE_KEY]["data"]["notes"][kitchen.id]["note"]
        == PRIVATE
    )


async def test_discard_forgets_missing_notes(
    hass: HomeAssistant,
    kitchen: er.RegistryEntry,
    setup_integration: SetupIntegration,
    hass_storage,
    hass_client,
) -> None:
    """The admin can accept the loss; the issue does not come back."""
    hass_storage[MIRROR_STORAGE_KEY] = storage(
        MIRROR_STORAGE_KEY, {kitchen.id: _mirror_record(kitchen)}
    )
    entry = await setup_integration()
    await _fix(hass_client, "discard")

    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MISSING_NOTES) is None
    assert hass_storage[MIRROR_STORAGE_KEY]["data"]["notes"] == {}
    notes_of(entry).async_check()
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MISSING_NOTES) is None


async def test_registry_rebuilt_with_new_id(
    hass: HomeAssistant,
    setup_integration: SetupIntegration,
    hass_storage,
    hass_client,
) -> None:
    """Same unique_id under a new registry id (registry rebuilt): notes move over."""
    registry = er.async_get(hass)
    new_entry = registry.async_get_or_create(
        "media_player", "cast", "tv-uid", suggested_object_id="tv"
    )
    old_id = "0123456789abcdef0123456789abcdef"
    record = _mirror_record(new_entry)
    hass_storage[MIRROR_STORAGE_KEY] = storage(MIRROR_STORAGE_KEY, {old_id: record})
    hass_storage[PRIVATE_STORAGE_KEY] = storage(
        PRIVATE_STORAGE_KEY, {old_id: _private_record(new_entry)}
    )
    entry = await setup_integration()
    notes = notes_of(entry)
    assert list(notes.missing) == [old_id]

    await _fix(hass_client, "restore")
    await hass.async_block_till_done()
    assert notes.async_get("media_player.tv") == {
        "entity_id": "media_player.tv",
        "registry_id": new_entry.id,
        "public": PUBLIC,
        "private": PRIVATE,
    }
    mirror = hass_storage[MIRROR_STORAGE_KEY]["data"]["notes"]
    assert list(mirror) == [new_entry.id]


@pytest.mark.usefixtures("kitchen")
async def test_note_removed_outside_the_notes_ui(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Something wiped the namespace while HA runs: Repairs offers it back."""
    entry = await setup_integration()
    notes = notes_of(entry)
    await notes.async_set("light.kitchen", public=PUBLIC)

    er.async_get(hass).async_update_entity_options("light.kitchen", DOMAIN, None)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MISSING_NOTES) is not None

    assert await notes.async_restore_missing() == 1
    await hass.async_block_till_done()
    assert notes.async_get("light.kitchen")["public"] == PUBLIC
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_MISSING_NOTES) is None


async def test_note_changed_while_not_running_follows_the_registry(
    hass: HomeAssistant,
    kitchen: er.RegistryEntry,
    setup_integration: SetupIntegration,
    hass_storage,
) -> None:
    """A newer registry text wins over the safety copy, without a Repairs issue."""
    er.async_get(hass).async_update_entity_options(
        "light.kitchen", DOMAIN, {"note": "newer"}
    )
    hass_storage[MIRROR_STORAGE_KEY] = storage(
        MIRROR_STORAGE_KEY, {kitchen.id: _mirror_record(kitchen, private=None)}
    )
    entry = await setup_integration()
    assert notes_of(entry).missing == {}
    [row] = notes_of(entry).async_list()
    assert row["public"] == "newer"


async def test_orphaned_notes_are_listed_and_can_be_forgotten(
    hass: HomeAssistant,
    kitchen: er.RegistryEntry,
    setup_integration: SetupIntegration,
    hass_ws_client,
) -> None:
    """Once the registry forgets a deleted entity, the notes stay listed until deleted."""
    entry = await setup_integration()
    notes = notes_of(entry)
    await notes.async_set("light.kitchen", public=PUBLIC, private=PRIVATE)
    registry = er.async_get(hass)
    registry.async_remove("light.kitchen")
    registry.deleted_entities.pop(("light", "test", "kitchen-uid"))
    notes.async_check()

    [row] = notes.async_list()
    assert row["state"] == "orphaned"
    assert (row["public"], row["private"]) == (PUBLIC, PRIVATE)
    assert notes.missing == {}

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/forget", "registry_id": kitchen.id}
    )
    assert (await client.receive_json())["success"]
    assert notes.async_list() == []


async def test_forget_refuses_existing_entities(
    hass: HomeAssistant,
    kitchen: er.RegistryEntry,
    setup_integration: SetupIntegration,
    hass_ws_client,
) -> None:
    """Notes of an entity that exists are edited, not forgotten."""
    await setup_integration()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/forget", "registry_id": kitchen.id}
    )
    assert (await client.receive_json())["error"]["code"] == "entity_exists"


async def test_frontend_report_raises_and_clears_warning(
    hass: HomeAssistant, setup_integration: SetupIntegration, hass_ws_client
) -> None:
    """A failed UI hook is a warning; a later success clears it."""
    await setup_integration()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/frontend_report",
            "hooks": {"more_info": False, "entities_table": True},
            "detail": "more_info: ha-more-info-info has no .content",
        }
    )
    assert (await client.receive_json())["success"]
    issue = repair_issue(hass, ISSUE_FRONTEND_HOOKS)
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    assert (issue.translation_placeholders or {})["hooks"] == "more_info"
    assert (issue.translation_placeholders or {})["frontend_version"]

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/frontend_report", "hooks": {"more_info": True}}
    )
    assert (await client.receive_json())["success"]
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FRONTEND_HOOKS) is None


async def test_missing_notes_listed_in_the_system_language(
    hass: HomeAssistant,
    kitchen: er.RegistryEntry,
    setup_integration: SetupIntegration,
    hass_storage: dict[str, Any],
) -> None:
    """Repairs placeholders are built on the server, in HA's language."""
    hass.config.language = "ru"
    hass_storage[MIRROR_STORAGE_KEY] = storage(
        MIRROR_STORAGE_KEY, {kitchen.id: _mirror_record(kitchen)}
    )
    await setup_integration()
    placeholders = repair_issue(hass, ISSUE_MISSING_NOTES).translation_placeholders
    expected = "- `light.kitchen`: общая заметка, приватная заметка"
    assert (placeholders or {})["entities"] == expected
