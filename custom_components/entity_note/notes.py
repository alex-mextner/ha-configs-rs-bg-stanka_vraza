"""
Notes on entities: public notes in the entity registry, private ones in our store.

Public note: ``options["entity_note"]["note"]`` on the entity registry entry. Core keeps
it through entity_id renames, delete/re-add (``deleted_entities``) and backups.

Private note (admins only): ``.storage/entity_note.private``, keyed by the registry
entry id. Core gives a re-added entity its old id back, so the note follows it.

Safety copy: ``.storage/entity_note.mirror`` holds both kinds, keyed the same way. It
is written before every change, so a note that vanishes from the registry or from the
private store without going through this module is found and offered for restore.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback, split_entity_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import UNDEFINED, UndefinedType
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ISSUE_FRONTEND_HOOKS,
    ISSUE_MAX_LISTED,
    ISSUE_MISSING_NOTES,
    ISSUE_URL,
    MAX_NOTE_LENGTH,
    MIRROR_SAVE_DELAY,
    MIRROR_STORAGE_KEY,
    NOTE_KIND_LABELS,
    OPTIONS_NOTE_KEY,
    PRIVATE_STORAGE_KEY,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_LOGGER = logging.getLogger(__name__)

type RegistryItem = er.RegistryEntry | er.DeletedRegistryEntry


class NoteState(StrEnum):
    """Where the entity a note belongs to is."""

    ACTIVE = "active"
    """In the entity registry."""
    DELETED = "deleted"
    """In ``deleted_entities``: the note comes back with the entity."""
    ORPHANED = "orphaned"
    """Gone from the registry; only this integration still has the note."""


class MirrorRecord(TypedDict):
    """Safety copy of the notes of one registry entry."""

    entity_id: str
    platform: str
    unique_id: str
    public: str | None
    private: str | None
    updated_at: str


class PrivateRecord(TypedDict):
    """A private note."""

    note: str
    entity_id: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class MissingNote:
    """A note the safety copy has and the registry or the private store lost."""

    registry_id: str
    """Key of the safety copy."""
    target_id: str
    """Entry to restore to: the same id, or a new entry with the same unique_id."""
    entity_id: str
    public: str | None
    private: str | None

    @property
    def kinds(self) -> list[str]:
        """Return which kinds of note are missing."""
        return [
            kind
            for kind, text in (("public", self.public), ("private", self.private))
            if text is not None
        ]


class NoteError(HomeAssistantError):
    """A note can't be written."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize with a websocket error code."""
        super().__init__(message)
        self.code = code


def normalize_note(text: str | None) -> str | None:
    """Strip outer whitespace and unify line breaks; empty text means no note."""
    if text is None:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > MAX_NOTE_LENGTH:
        msg = f"A note can have at most {MAX_NOTE_LENGTH} characters"
        raise NoteError(code="note_too_long", message=msg)
    return text or None


def public_note(options: Mapping[str, Mapping[str, Any]] | UndefinedType) -> str | None:
    """Return the public note stored in registry options, if any."""
    if options is UNDEFINED:
        return None
    value = options.get(DOMAIN, {}).get(OPTIONS_NOTE_KEY)
    return value if isinstance(value, str) and value else None


class EntityNotes:
    """Read and write notes, and keep the safety copy in step."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self._private_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, PRIVATE_STORAGE_KEY, private=True, atomic_writes=True
        )
        self._mirror_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, MIRROR_STORAGE_KEY, private=True, atomic_writes=True
        )
        self._private: dict[str, PrivateRecord] = {}
        self._mirror: dict[str, MirrorRecord] = {}
        self._checked = False
        self._listeners: set[Callable[[], None]] = set()
        self.missing: dict[str, MissingNote] = {}
        self.hooks: dict[str, dict[str, Any]] = {}
        self.frontend_version: str | None = None

    # ------------------------------------------------------------------ setup

    async def async_load(self) -> None:
        """Load the private notes and the safety copy."""
        private = await self._private_store.async_load() or {}
        self._private = dict(private.get("notes", {}))
        mirror = await self._mirror_store.async_load()
        if mirror is None:
            # First start, or the copy itself was lost: rebuild it from what exists.
            self._async_adopt_unmirrored()
            await self._async_save_mirror()
        else:
            self._mirror = dict(mirror.get("notes", {}))

    @callback
    def async_start(self) -> Callable[[], None]:
        """Follow registry changes and check the notes once HA has started."""
        unsub_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, self._async_registry_updated
        )
        unsub_started: Callable[[], None] | None = None

        @callback
        def _started(_event: Event) -> None:
            nonlocal unsub_started
            unsub_started = None
            self.async_check()

        if self.hass.is_running:
            self.async_check()
        else:
            unsub_started = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _started
            )

        @callback
        def _stop() -> None:
            unsub_registry()
            if unsub_started is not None:
                unsub_started()

        return _stop

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` after any note changes."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def _async_notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ------------------------------------------------------------------ reads

    @callback
    def async_get(self, entity_id: str) -> dict[str, Any]:
        """Return both notes of an entity."""
        entry = self._registry_entry(entity_id)
        private = self._private.get(entry.id)
        return {
            "entity_id": entry.entity_id,
            "registry_id": entry.id,
            "public": public_note(entry.options),
            "private": private["note"] if private else None,
        }

    @callback
    def async_list(self) -> list[dict[str, Any]]:
        """Return every note: active, of deleted entities, and orphaned."""
        registry = er.async_get(self.hass)
        rows: dict[str, dict[str, Any]] = {}
        items: list[tuple[RegistryItem, NoteState]] = [
            *((entry, NoteState.ACTIVE) for entry in registry.entities.values()),
            *((item, NoteState.DELETED) for item in registry.deleted_entities.values()),
        ]
        for item, state in items:
            public = public_note(item.options)
            private = self._private.get(item.id)
            if public is not None or private is not None:
                rows[item.id] = self._row(
                    item.id,
                    item.entity_id,
                    state,
                    public,
                    private["note"] if private else None,
                )
        for registry_id, record in self._mirror.items():
            private = self._private.get(registry_id)
            private_text = private["note"] if private else record["private"]
            if registry_id in rows or (record["public"] or private_text) is None:
                continue
            rows[registry_id] = self._row(
                registry_id,
                record["entity_id"],
                NoteState.ORPHANED,
                record["public"],
                private_text,
            )
        for registry_id, private in self._private.items():
            if registry_id not in rows:
                rows[registry_id] = self._row(
                    registry_id,
                    private["entity_id"],
                    NoteState.ORPHANED,
                    None,
                    private["note"],
                )
        return list(rows.values())

    def _row(
        self,
        registry_id: str,
        entity_id: str,
        state: NoteState,
        public: str | None,
        private: str | None,
    ) -> dict[str, Any]:
        record = self._mirror.get(registry_id)
        return {
            "registry_id": registry_id,
            "entity_id": entity_id,
            "state": state.value,
            "public": public,
            "private": private,
            "updated_at": record["updated_at"] if record else None,
        }

    @callback
    def async_counts(self) -> dict[str, int]:
        """Return how many notes of each kind exist (for diagnostics)."""
        counts = {str(key): 0 for key in ("public", "private", *NoteState)}
        for row in self.async_list():
            counts[row["state"]] += 1
            counts["public"] += row["public"] is not None
            counts["private"] += row["private"] is not None
        return counts

    # ----------------------------------------------------------------- writes

    async def async_set(
        self,
        entity_id: str,
        *,
        public: str | None | UndefinedType = UNDEFINED,
        private: str | None | UndefinedType = UNDEFINED,
    ) -> dict[str, Any]:
        """Write the public and/or private note of an entity; empty text deletes."""
        entry = self._registry_entry(entity_id)
        old_public = public_note(entry.options)
        old_private = self._private.get(entry.id)
        new_public = old_public if public is UNDEFINED else normalize_note(public)
        new_private = (
            (old_private["note"] if old_private else None)
            if private is UNDEFINED
            else normalize_note(private)
        )
        now = dt_util.utcnow().isoformat()

        # 1. The safety copy first: if HA stops half-way, the startup check sees
        #    the difference and offers to restore.
        if new_public is None and new_private is None:
            self._mirror.pop(entry.id, None)
        else:
            self._mirror[entry.id] = MirrorRecord(
                entity_id=entry.entity_id,
                platform=entry.platform,
                unique_id=entry.unique_id,
                public=new_public,
                private=new_private,
                updated_at=now,
            )
        self.missing.pop(entry.id, None)
        await self._async_save_mirror()

        # 2. The private store.
        if private is not UNDEFINED:
            if new_private is None:
                self._private.pop(entry.id, None)
            else:
                self._private[entry.id] = PrivateRecord(
                    note=new_private, entity_id=entry.entity_id, updated_at=now
                )
            await self._async_save_private()

        # 3. The registry (it saves itself a few seconds later).
        if new_public != old_public:
            er.async_get(self.hass).async_update_entity_options(
                entry.entity_id,
                DOMAIN,
                {OPTIONS_NOTE_KEY: new_public} if new_public is not None else None,
            )

        self._async_update_missing_issue()
        self._async_notify()
        return self.async_get(entry.entity_id)

    async def async_forget(self, registry_id: str) -> None:
        """Delete the notes kept for an entity that is gone from the registry."""
        if er.async_get(self.hass).async_get(registry_id) is not None:
            msg = "The entity exists: edit its notes instead"
            raise NoteError(code="entity_exists", message=msg)
        if registry_id not in self._mirror and registry_id not in self._private:
            msg = "No notes are kept for this entry"
            raise NoteError(code="not_found", message=msg)
        self._mirror.pop(registry_id, None)
        self.missing.pop(registry_id, None)
        await self._async_save_mirror()
        if self._private.pop(registry_id, None) is not None:
            await self._async_save_private()
        self._async_update_missing_issue()
        self._async_notify()

    # --------------------------------------------------------- safety checks

    @callback
    def async_check(self) -> None:
        """Compare the safety copy with the registry and the private store."""
        self._checked = True
        registry = er.async_get(self.hass)
        deleted = {item.id: item for item in registry.deleted_entities.values()}
        changed = self._async_adopt_unmirrored()
        self.missing = {}
        for registry_id in list(self._mirror):
            changed |= self._check_record(registry, deleted, registry_id)
        if changed:
            self._async_schedule_mirror_save()
        self._async_update_missing_issue()

    def _check_record(
        self,
        registry: er.EntityRegistry,
        deleted: Mapping[str, er.DeletedRegistryEntry],
        registry_id: str,
    ) -> bool:
        """Check one safety-copy record; return True if the record was updated."""
        record = self._mirror[registry_id]
        item: RegistryItem | None = registry.async_get(registry_id) or deleted.get(
            registry_id
        )
        if item is None:
            return self._check_recreated(registry, registry_id, record)

        changed = False
        if item.entity_id != record["entity_id"]:
            record["entity_id"] = item.entity_id
            changed = True

        lost_public = None
        registry_public = public_note(item.options)
        if record["public"] is not None and registry_public is None:
            # A deleted entity can't take the note back until it returns.
            if isinstance(item, er.RegistryEntry):
                lost_public = record["public"]
        elif registry_public != record["public"]:
            # Changed while this integration was not running: the registry wins.
            record["public"] = registry_public
            changed = True

        lost_private = None
        private = self._private.get(registry_id)
        if record["private"] is not None and private is None:
            lost_private = record["private"]
        elif private is not None and private["note"] != record["private"]:
            record["private"] = private["note"]
            changed = True

        if lost_public is not None or lost_private is not None:
            self.missing[registry_id] = MissingNote(
                registry_id, registry_id, item.entity_id, lost_public, lost_private
            )
        return changed

    def _check_recreated(
        self, registry: er.EntityRegistry, registry_id: str, record: MirrorRecord
    ) -> bool:
        """Find a note whose registry entry was replaced by a new one (new id)."""
        if not record["platform"]:
            return False
        new_entity_id = registry.async_get_entity_id(
            split_entity_id(record["entity_id"])[0],
            record["platform"],
            record["unique_id"],
        )
        entry = registry.async_get(new_entity_id) if new_entity_id else None
        if entry is None:
            return False  # Orphaned: listed in the Notes panel, nothing to restore.
        lost_public = record["public"] if public_note(entry.options) is None else None
        kept_private = self._private.get(registry_id)
        lost_private = (
            (kept_private["note"] if kept_private else record["private"])
            if entry.id not in self._private
            else None
        )
        if lost_public is None and lost_private is None:
            # The new entry already has its notes: drop the stale copy.
            del self._mirror[registry_id]
            self._private.pop(registry_id, None)
            return True
        self.missing[registry_id] = MissingNote(
            registry_id, entry.id, entry.entity_id, lost_public, lost_private
        )
        return False

    @callback
    def _async_check_entry(self, entry: er.RegistryEntry) -> None:
        """Check the safety copy for one entity that was just created."""
        registry = er.async_get(self.hass)
        domain = entry.domain
        for registry_id, record in list(self._mirror.items()):
            if registry_id == entry.id or (
                record["platform"] == entry.platform
                and record["unique_id"] == entry.unique_id
                and split_entity_id(record["entity_id"])[0] == domain
            ):
                self.missing.pop(registry_id, None)
                if self._check_record(registry, {}, registry_id):
                    self._async_schedule_mirror_save()
        self._async_update_missing_issue()

    @callback
    def _async_adopt_unmirrored(self) -> bool:
        """Copy notes the safety copy doesn't have yet (first start, or old copy)."""
        registry = er.async_get(self.hass)
        changed = False
        now = dt_util.utcnow().isoformat()
        items: dict[str, RegistryItem] = {
            item.id: item for item in registry.deleted_entities.values()
        }
        items.update((entry.id, entry) for entry in registry.entities.values())
        for registry_id, item in items.items():
            public = public_note(item.options)
            private = self._private.get(registry_id)
            if registry_id in self._mirror or (public is None and private is None):
                continue
            self._mirror[registry_id] = MirrorRecord(
                entity_id=item.entity_id,
                platform=item.platform,
                unique_id=item.unique_id,
                public=public,
                private=private["note"] if private else None,
                updated_at=private["updated_at"] if private else now,
            )
            changed = True
        for registry_id, private in self._private.items():
            if registry_id not in self._mirror:
                self._mirror[registry_id] = MirrorRecord(
                    entity_id=private["entity_id"],
                    platform="",
                    unique_id="",
                    public=None,
                    private=private["note"],
                    updated_at=private["updated_at"],
                )
                changed = True
        return changed

    async def async_restore_missing(self) -> int:
        """Put back every missing note; return how many entities got notes back."""
        registry = er.async_get(self.hass)
        restored = 0
        now = dt_util.utcnow().isoformat()
        for missing in list(self.missing.values()):
            target = registry.async_get(missing.target_id)
            record = self._mirror.get(missing.registry_id)
            if target is None or record is None:
                continue
            del self.missing[missing.registry_id]
            if missing.target_id != missing.registry_id:
                del self._mirror[missing.registry_id]
                old_private = self._private.pop(missing.registry_id, None)
                if missing.private is None and old_private is not None:
                    self._private[target.id] = old_private
            self._mirror[target.id] = MirrorRecord(
                entity_id=target.entity_id,
                platform=target.platform,
                unique_id=target.unique_id,
                public=missing.public or public_note(target.options),
                private=missing.private or record["private"],
                updated_at=now,
            )
            if missing.private is not None:
                self._private[target.id] = PrivateRecord(
                    note=missing.private, entity_id=target.entity_id, updated_at=now
                )
            restored += 1
        await self._async_save_mirror()
        await self._async_save_private()
        for registry_id, record in self._mirror.items():
            target = registry.async_get(registry_id)
            if (
                target is not None
                and record["public"] is not None
                and public_note(target.options) is None
            ):
                registry.async_update_entity_options(
                    target.entity_id, DOMAIN, {OPTIONS_NOTE_KEY: record["public"]}
                )
        self._async_update_missing_issue()
        self._async_notify()
        return restored

    async def async_discard_missing(self) -> int:
        """Accept the loss: drop the missing notes from the safety copy."""
        discarded = len(self.missing)
        for missing in self.missing.values():
            record = self._mirror.get(missing.registry_id)
            if record is None:
                continue
            if missing.public is not None:
                record["public"] = None
            if missing.private is not None:
                record["private"] = None
            if missing.target_id != missing.registry_id or (
                record["public"] is None and record["private"] is None
            ):
                del self._mirror[missing.registry_id]
                self._private.pop(missing.registry_id, None)
        self.missing = {}
        await self._async_save_mirror()
        await self._async_save_private()
        self._async_update_missing_issue()
        self._async_notify()
        return discarded

    # --------------------------------------------------------- registry events

    @callback
    def _async_registry_updated(
        self, event: Event[er.EventEntityRegistryUpdatedData]
    ) -> None:
        """Keep the safety copy in step with registry changes."""
        data = event.data
        if data["action"] == "remove":
            # The options move to deleted_entities under the same id.
            self._async_notify()
            return
        entry = er.async_get(self.hass).async_get(data["entity_id"])
        if entry is None:
            return
        if data["action"] == "update":
            changes = data["changes"]
            if "entity_id" in changes:
                self._async_renamed(entry)
            if "options" in changes:
                self._async_options_changed(entry)
        elif self._checked:
            # Created (or re-added from deleted_entities).
            self._async_check_entry(entry)
            self._async_notify()

    @callback
    def _async_options_changed(self, entry: er.RegistryEntry) -> None:
        record = self._mirror.get(entry.id)
        registry_public = public_note(entry.options)
        mirror_public = record["public"] if record else None
        if registry_public == mirror_public:
            return  # Our own write, or another namespace changed.
        if registry_public is None:
            _LOGGER.warning(
                "The public note of %s disappeared without being deleted in the"
                " notes UI; see Settings > Repairs",
                entry.entity_id,
            )
            self.missing[entry.id] = MissingNote(
                entry.id, entry.id, entry.entity_id, mirror_public, None
            )
            self._async_update_missing_issue()
        else:
            # Written with config/entity_registry/update (admin only): keep it.
            private = self._private.get(entry.id)
            self._mirror[entry.id] = MirrorRecord(
                entity_id=entry.entity_id,
                platform=entry.platform,
                unique_id=entry.unique_id,
                public=registry_public,
                private=private["note"] if private else None,
                updated_at=dt_util.utcnow().isoformat(),
            )
            self._async_schedule_mirror_save()
        self._async_notify()

    @callback
    def _async_renamed(self, entry: er.RegistryEntry) -> None:
        if (record := self._mirror.get(entry.id)) is not None:
            record["entity_id"] = entry.entity_id
            self._async_schedule_mirror_save()
        if (private := self._private.get(entry.id)) is not None:
            private["entity_id"] = entry.entity_id
            self._private_store.async_delay_save(self._private_data, MIRROR_SAVE_DELAY)
        if (old := self.missing.get(entry.id)) is not None:
            self.missing[entry.id] = MissingNote(
                old.registry_id, old.target_id, entry.entity_id, old.public, old.private
            )
            self._async_update_missing_issue()
        self._async_notify()

    # --------------------------------------------------------- frontend hooks

    @callback
    def async_frontend_report(
        self, frontend_version: str | None, hooks: Mapping[str, bool], detail: str
    ) -> None:
        """Record which UI hooks attached; raise or clear the Repairs warning."""
        now = dt_util.utcnow().isoformat()
        if frontend_version:
            self.frontend_version = frontend_version
        for name, ok in hooks.items():
            self.hooks[name] = {"ok": ok, "at": now, "detail": "" if ok else detail}
        failed = sorted(name for name, state in self.hooks.items() if not state["ok"])
        if not failed:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_FRONTEND_HOOKS)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_FRONTEND_HOOKS,
            is_fixable=False,
            is_persistent=False,
            learn_more_url=ISSUE_URL,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_FRONTEND_HOOKS,
            translation_placeholders={
                "hooks": ", ".join(failed),
                "frontend_version": self.frontend_version or "?",
            },
        )

    # ---------------------------------------------------------------- helpers

    def _registry_entry(self, entity_id: str) -> er.RegistryEntry:
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None:
            msg = f"{entity_id} is not in the entity registry (it has no unique ID)"
            raise NoteError(code="not_found", message=msg)
        return entry

    @callback
    def missing_placeholders(self) -> dict[str, str]:
        """Return the Repairs placeholders: how many, and which entities."""
        labels = NOTE_KIND_LABELS.get(self.hass.config.language, NOTE_KIND_LABELS["en"])
        listed = list(self.missing.values())[:ISSUE_MAX_LISTED]
        lines = [
            f"- `{missing.entity_id}`: "
            + (", ".join(labels[kind] for kind in missing.kinds) or "-")
            for missing in listed
        ]
        if (extra := len(self.missing) - len(listed)) > 0:
            lines.append(f"- +{extra}")
        return {"count": str(len(self.missing)), "entities": "\n".join(lines)}

    def _async_update_missing_issue(self) -> None:
        if not self.missing:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_MISSING_NOTES)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_MISSING_NOTES,
            is_fixable=True,
            is_persistent=False,
            learn_more_url=ISSUE_URL,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_MISSING_NOTES,
            translation_placeholders=self.missing_placeholders(),
        )

    def _mirror_data(self) -> dict[str, Any]:
        return {"notes": self._mirror}

    def _private_data(self) -> dict[str, Any]:
        return {"notes": self._private}

    async def _async_save_mirror(self) -> None:
        await self._mirror_store.async_save(self._mirror_data())

    async def _async_save_private(self) -> None:
        await self._private_store.async_save(self._private_data())

    @callback
    def _async_schedule_mirror_save(self) -> None:
        self._mirror_store.async_delay_save(self._mirror_data, MIRROR_SAVE_DELAY)
