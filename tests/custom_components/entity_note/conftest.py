# ruff: noqa: S101
"""Fixtures for the entity_note tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import pytest
from awesomeversion import AwesomeVersion
from homeassistant import const as ha_const
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.entity_note.notes import EntityNotes

# These tests pin the HA release running here (requirements/test-entity-note.txt,
# `make test-entity-note`). The shared venv of `make test` pins an older release
# that the integration does not support: collect nothing there.
MIN_HA_VERSION = "2026.9.0"
if AwesomeVersion(ha_const.__version__) < AwesomeVersion(MIN_HA_VERSION):
    collect_ignore_glob = ["test_*.py"]

DOMAIN = "entity_note"

type SetupIntegration = Callable[[], Awaitable[MockConfigEntry]]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load integrations from custom_components."""


@pytest.fixture
def kitchen(hass: HomeAssistant) -> er.RegistryEntry:
    """Return a registry entry with a unique ID."""
    return er.async_get(hass).async_get_or_create(
        "light", "test", "kitchen-uid", suggested_object_id="kitchen"
    )


@pytest.fixture
def setup_integration(hass: HomeAssistant) -> SetupIntegration:
    """Return a coroutine that adds and loads the config entry."""

    async def _setup() -> MockConfigEntry:
        entry = MockConfigEntry(domain=DOMAIN, title="Entity notes")
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup


def notes_of(entry: MockConfigEntry) -> EntityNotes:
    """Return the runtime notes object of a loaded entry."""
    return entry.runtime_data


def storage(key: str, notes: dict[str, Any]) -> dict[str, Any]:
    """Return a hass_storage record for one of our stores."""
    return {"version": 1, "minor_version": 1, "key": key, "data": {"notes": notes}}


def registry_entry(hass: HomeAssistant, entity_id: str) -> er.RegistryEntry:
    """Return a registry entry that must exist."""
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None, entity_id
    return entry


def repair_issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry:
    """Return one of our Repairs issues that must exist."""
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None, issue_id
    return issue
