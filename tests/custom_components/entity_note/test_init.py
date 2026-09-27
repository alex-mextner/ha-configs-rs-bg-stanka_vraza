# ruff: noqa: S101
"""Config flow, setup/unload and the served frontend module."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from homeassistant import config_entries
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, DATA_PANELS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from custom_components.entity_note.const import (
    DOMAIN,
    MODULE_FILENAME,
    PANEL_URL_PATH,
    STATIC_URL_PATH,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

    from .conftest import SetupIntegration


async def test_config_flow_single_entry(hass: HomeAssistant) -> None:
    """The flow asks once, creates one entry, and refuses a second one."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("title") == "Entity notes"
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "single_instance_allowed"


async def test_entry_title_follows_language(hass: HomeAssistant) -> None:
    """A Russian HA gets a Russian entry title."""
    hass.config.language = "ru"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result.get("title") == "Заметки к сущностям"


async def test_setup_adds_module_and_admin_panel(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """The JS module is loaded on every page; the panel is admin-only."""
    entry = await setup_integration()
    assert entry.state is ConfigEntryState.LOADED

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    module_urls = [url for url in urls if url.startswith(STATIC_URL_PATH)]
    assert len(module_urls) == 1
    assert module_urls[0].startswith(f"{STATIC_URL_PATH}/{MODULE_FILENAME}?v=")

    panel = hass.data[DATA_PANELS][PANEL_URL_PATH]
    assert panel.require_admin is True
    assert panel.config is not None
    assert panel.config["_panel_custom"]["name"] == "entity-note-panel"
    assert panel.config["_panel_custom"]["module_url"] == module_urls[0]


async def test_unload_removes_module_and_panel(
    hass: HomeAssistant, setup_integration: SetupIntegration
) -> None:
    """Unloading takes the UI away and leaves the notes alone."""
    entry = await setup_integration()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert PANEL_URL_PATH not in hass.data[DATA_PANELS]
    assert not [
        url
        for url in hass.data[DATA_EXTRA_MODULE_URL].urls
        if url.startswith(STATIC_URL_PATH)
    ]

    # Loading again must not fail on the static route registered the first time.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_module_is_served(
    setup_integration: SetupIntegration, hass_client: ClientSessionGenerator
) -> None:
    """The module URL returns the script."""
    await setup_integration()
    client = await hass_client()
    response = await client.get(f"{STATIC_URL_PATH}/{MODULE_FILENAME}")
    assert response.status == HTTPStatus.OK
    body = await response.text()
    assert 'define("entity-note-panel", EntityNotePanel)' in body
