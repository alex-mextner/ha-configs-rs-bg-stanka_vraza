"""Config flow: one entry, nothing to configure."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN

ENTRY_TITLES = {"en": "Entity notes", "ru": "Заметки к сущностям"}


class EntityNoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the integration (the manifest allows a single entry)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm and create the entry."""
        if user_input is None:
            return self.async_show_form(step_id="user")
        title = ENTRY_TITLES.get(self.hass.config.language, ENTRY_TITLES["en"])
        return self.async_create_entry(title=title, data={})
