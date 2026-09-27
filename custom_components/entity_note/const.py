"""Constants for the entity_note integration."""

from typing import Final

DOMAIN: Final = "entity_note"

# Public notes live in the entity registry entry: options[DOMAIN][OPTIONS_NOTE_KEY].
OPTIONS_NOTE_KEY: Final = "note"

# Private notes (admins only) and the safety copy of all notes, keyed by the
# entity registry entry id, which survives entity_id renames and delete/re-add.
PRIVATE_STORAGE_KEY: Final = f"{DOMAIN}.private"
MIRROR_STORAGE_KEY: Final = f"{DOMAIN}.mirror"
STORAGE_VERSION: Final = 1
MIRROR_SAVE_DELAY: Final = 1

# Longer text is refused. Public notes travel in every config/entity_registry/list
# response, so a pasted log must not end up there.
MAX_NOTE_LENGTH: Final = 10000

STATIC_URL_PATH: Final = "/entity_note_static"
MODULE_FILENAME: Final = "entity-note.js"
PANEL_URL_PATH: Final = "entity-notes"
PANEL_COMPONENT: Final = "entity-note-panel"
PANEL_ICON: Final = "mdi:note-text-outline"
PANEL_TITLES: Final = {"en": "Notes", "ru": "Заметки"}

ISSUE_MISSING_NOTES: Final = "missing_notes"
ISSUE_FRONTEND_HOOKS: Final = "frontend_hooks_failed"
ISSUE_URL: Final = (
    "https://github.com/alex-mextner/ha-configs-rs-bg-stanka_vraza/issues/3"
)
# How many entity ids a Repairs issue lists before "and N more".
ISSUE_MAX_LISTED: Final = 10
# Repairs placeholders are built on the server, so they follow HA's system language.
NOTE_KIND_LABELS: Final = {
    "en": {"public": "public note", "private": "private note"},
    "ru": {"public": "общая заметка", "private": "приватная заметка"},
}
