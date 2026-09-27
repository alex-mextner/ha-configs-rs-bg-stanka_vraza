"""Serve the JS module, load it on every page and register the admin Notes panel."""

from __future__ import annotations

import hashlib
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from .const import (
    MODULE_FILENAME,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_TITLES,
    PANEL_URL_PATH,
    STATIC_URL_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .notes import EntityNotes

FRONTEND_DIR = Path(__file__).parent / "frontend"
# Static routes can't be removed, so they are registered once per HA run.
DATA_STATIC_REGISTERED: HassKey[bool] = HassKey("entity_note_static_registered")


def _module_version(path: Path) -> str:
    """Return a short content hash, so browsers load a changed module."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _frontend_package_version() -> str | None:
    try:
        return metadata.version("home-assistant-frontend")
    except metadata.PackageNotFoundError:
        return None


async def async_register_frontend(
    hass: HomeAssistant, notes: EntityNotes
) -> Callable[[], None]:
    """Add the module and the panel; return a callback that removes both."""
    if not hass.data.get(DATA_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL_PATH, str(FRONTEND_DIR), cache_headers=True)]
        )
        hass.data[DATA_STATIC_REGISTERED] = True

    version = await hass.async_add_executor_job(
        _module_version, FRONTEND_DIR / MODULE_FILENAME
    )
    notes.frontend_version = await hass.async_add_executor_job(
        _frontend_package_version
    )
    url = f"{STATIC_URL_PATH}/{MODULE_FILENAME}?v={version}"
    frontend.add_extra_js_url(hass, url)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=PANEL_TITLES.get(hass.config.language, PANEL_TITLES["en"]),
        sidebar_icon=PANEL_ICON,
        module_url=url,
        require_admin=True,
    )

    @callback
    def _unregister() -> None:
        frontend.remove_extra_js_url(hass, url)
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)

    return _unregister
