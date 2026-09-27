"""Repairs: restore notes that vanished without being deleted in the notes UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.repairs import RepairsFlow

from .const import DOMAIN, ISSUE_MISSING_NOTES

if TYPE_CHECKING:
    from homeassistant import data_entry_flow
    from homeassistant.core import HomeAssistant

    from .notes import EntityNotes


def _loaded_notes(hass: HomeAssistant) -> EntityNotes | None:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


class MissingNotesRepairFlow(RepairsFlow):
    """Offer to restore the missing notes from the safety copy, or to forget them."""

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> data_entry_flow.FlowResult:
        """Choose restore or discard."""
        notes = _loaded_notes(self.hass)
        if notes is None or not notes.missing:
            return self.async_abort(reason="nothing_missing")
        return self.async_show_menu(
            step_id="init",
            menu_options=["restore", "discard"],
            description_placeholders=notes.missing_placeholders(),
        )

    async def async_step_restore(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002
    ) -> data_entry_flow.FlowResult:
        """Put the notes back."""
        notes = _loaded_notes(self.hass)
        if notes is None:
            return self.async_abort(reason="nothing_missing")
        await notes.async_restore_missing()
        return self.async_create_entry(data={})

    async def async_step_discard(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Ask once more, then forget the missing notes."""
        notes = _loaded_notes(self.hass)
        if notes is None:
            return self.async_abort(reason="nothing_missing")
        if user_input is None:
            return self.async_show_form(
                step_id="discard",
                description_placeholders=notes.missing_placeholders(),
            )
        await notes.async_discard_missing()
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,
    data: dict[str, str | int | float | None] | None,  # noqa: ARG001
) -> RepairsFlow:
    """Create the fix flow for a fixable issue."""
    if issue_id != ISSUE_MISSING_NOTES:
        msg = f"Unknown issue {issue_id}"
        raise ValueError(msg)
    return MissingNotesRepairFlow()
