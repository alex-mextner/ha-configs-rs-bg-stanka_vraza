"""Diagnostics: counts and hook status only, never the text of a note."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import EntityNoteConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: EntityNoteConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics. Private notes must not leak into a shared file."""
    notes = entry.runtime_data
    return {
        "counts": notes.async_counts(),
        "notes": [
            {
                "entity_id": row["entity_id"],
                "state": row["state"],
                "public_length": len(row["public"] or ""),
                "private_length": len(row["private"] or ""),
                "updated_at": row["updated_at"],
            }
            for row in notes.async_list()
        ],
        "missing": [
            {"entity_id": missing.entity_id, "kinds": missing.kinds}
            for missing in notes.missing.values()
        ],
        "frontend": {"version": notes.frontend_version, "hooks": notes.hooks},
    }
