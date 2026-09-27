# Entity notes

Custom integration `entity_note` ([#3](https://github.com/alex-mextner/ha-configs-rs-bg-stanka_vraza/issues/3),
variant A: no core patch). A note says why an entity is set up the way it is.

## What it shows

- **Entity dialog**, main view, below the controls: the public note, then (admins only) the
  private note, marked with a lock and "Private note, only admins". Long notes are cut after
  8 lines with "Show more". Admins get "Add note" / "Edit" buttons; saving empty text deletes
  the note. Non-admins see the public note read-only and nothing else.
- **Settings > Entities**: a note icon after the entity name (a lock when there is only a
  private note), with the note as tooltip. The search box also matches note text, private
  notes included (the page is admin-only).
- **Notes** sidebar panel (admins only): every note, with search, and the notes of removed
  entities, which can be deleted there. It uses no HA internals, so it keeps working when the
  hooks above break.
- Plain text, no markdown. Labels in English and Russian, following the user's language.

## Where the notes live

| | Public note | Private note |
|---|---|---|
| Stored in | entity registry entry, `options.entity_note.note` | `.storage/entity_note.private`, keyed by the registry entry id |
| Readable by | every logged-in user (`config/entity_registry/get`) | admins only (`entity_note/*` websocket commands) |
| Writable by | admins | admins |

Both survive entity_id renames, delete and re-add (HA gives a returning entity its old registry
id), and backups (both are in `.storage`). Neither goes to Assist or LLM integrations: they are
not state attributes, and a test checks the Assist API prompt and its live-context tool.

## Safety net

- `.storage/entity_note.mirror` is a copy of both kinds of notes, written before every change.
- At startup, and when an entity is (re)created, it is compared with the registry and the
  private store. Notes that disappeared without being deleted in the notes UI raise a Repairs
  issue (error). Its fix flow restores them, also onto a new registry entry with the same
  unique_id, or forgets them.
- The JS module hooks internal frontend elements (`ha-more-info-info`, `ha-config-entities`).
  Each hook checks what it attaches to; an admin's browser reports failures, which raise a
  Repairs warning naming the hook and the frontend version. Only the display can break.
- Diagnostics contain counts and lengths, never note text.

## Websocket API (all admin-only)

`entity_note/get`, `entity_note/list`, `entity_note/update` (`public` / `private`; empty or
`null` deletes), `entity_note/forget` (notes of a removed entity), `entity_note/subscribe`,
`entity_note/frontend_report`.

## Development

- Tests: `make test-entity-note`. They run in their own venv `hga-entity-note`, pinned in
  `requirements/test-entity-note.txt` to the HA release running here; bump those pins with
  every HA update. `make test` (older HA pin) skips them.
- Screenshots: [screenshots/entity-notes](screenshots/entity-notes/), taken in a throwaway
  HA 2026.9.3 container with test users.
