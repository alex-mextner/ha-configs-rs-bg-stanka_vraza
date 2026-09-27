// Entity notes: the UI of the entity_note integration.
//
// Loaded on every page with frontend.add_extra_js_url. It adds:
// - a notes block at the end of the entity dialog's main view (hook on ha-more-info-info);
// - a note icon after the entity name and note search in Settings > Entities
//   (hook on ha-config-entities);
// - the admin "Notes" sidebar panel (entity-note-panel), which touches no HA internals.
//
// The hooks rely on internal frontend elements. Each one checks what it attaches to and
// reports the result, so a frontend update can break the display but never the notes.
// Note text is user content: it is only ever inserted as text nodes.

const DOMAIN = "entity_note";
const MAX_LENGTH = 10000;
const TOOLTIP_LENGTH = 250;
const CLAMP_LINES = 8;

const ICONS = {
  note: "M9,22A1,1 0 0,1 8,21V18H4A2,2 0 0,1 2,16V4C2,2.89 2.9,2 4,2H20A2,2 0 0,1 22,4V16A2,2 0 0,1 20,18H13.9L10.2,21.71C10,21.9 9.75,22 9.5,22V22H9M10,16V19.08L13.08,16H20V4H4V16H10M6,7H18V9H6V7M6,11H15V13H6V11Z",
  add: "M9,22A1,1 0 0,1 8,21V18H4A2,2 0 0,1 2,16V4C2,2.89 2.9,2 4,2H20A2,2 0 0,1 22,4V16A2,2 0 0,1 20,18H13.9L10.2,21.71C10,21.9 9.75,22 9.5,22V22H9M10,16V19.08L13.08,16H20V4H4V16H10M11,6H13V9H16V11H13V14H11V11H8V9H11V6Z",
  lock: "M12,17C10.89,17 10,16.1 10,15C10,13.89 10.89,13 12,13A2,2 0 0,1 14,15A2,2 0 0,1 12,17M18,20V10H6V20H18M18,8A2,2 0 0,1 20,10V20A2,2 0 0,1 18,22H6C4.89,22 4,21.1 4,20V10C4,8.89 4.89,8 6,8H7V6A5,5 0 0,1 12,1A5,5 0 0,1 17,6V8H18M12,3A3,3 0 0,0 9,6V8H15V6A3,3 0 0,0 12,3Z",
  search:
    "M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z",
  menu: "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z",
  close:
    "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  alert:
    "M11,15H13V17H11V15M11,7H13V13H11V7M12,2C6.47,2 2,6.5 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20Z",
  empty:
    "M15 3H5A2 2 0 0 0 3 5V19A2 2 0 0 0 5 21H19A2 2 0 0 0 21 19V9L15 3M19 19H5V5H14V10H19M17 14H7V12H17M14 17H7V15H14",
};

const STRINGS = {
  en: {
    note: "Note",
    private_note: "Private note, only admins",
    add_note: "Add note",
    add_private_note: "Add private note",
    edit: "Edit",
    edit_note: "Edit note",
    edit_private_note: "Edit private note",
    public_helper: "Visible to all users of this Home Assistant. Not shared with voice assistants.",
    private_helper: "Only administrators see it. Not shared with voice assistants.",
    empty_removes: "Save empty text to delete the note.",
    save: "Save",
    cancel: "Cancel",
    delete: "Delete",
    show_more: "Show more",
    show_less: "Show less",
    too_long: "Too long: at most {max} characters.",
    save_failed: "The note was not saved: {error}",
    load_failed: "Notes could not be loaded: {error}",
    panel_title: "Notes",
    menu: "Menu",
    search: "Search notes",
    clear_search: "Clear search",
    total: "Notes: {count}",
    empty: "No notes yet. Open an entity and add a note below its controls.",
    no_results: "No notes match “{query}”.",
    removed_section: "Notes of removed entities",
    state_deleted: "Entity removed. Its notes come back if it is added again.",
    state_orphaned: "The entity no longer exists. Only these notes are left.",
    forget: "Delete notes",
    forget_title: "Delete these notes?",
    forget_text: "The notes of {entity} will be deleted. This cannot be undone.",
    open_entity: "Open {entity}",
  },
  ru: {
    note: "Заметка",
    private_note: "Приватная заметка, только для админов",
    add_note: "Добавить заметку",
    add_private_note: "Добавить приватную заметку",
    edit: "Изменить",
    edit_note: "Изменить заметку",
    edit_private_note: "Изменить приватную заметку",
    public_helper:
      "Видна всем пользователям этого Home Assistant. Голосовым ассистентам не передаётся.",
    private_helper: "Видна только администраторам. Голосовым ассистентам не передаётся.",
    empty_removes: "Сохраните пустой текст, чтобы удалить заметку.",
    save: "Сохранить",
    cancel: "Отмена",
    delete: "Удалить",
    show_more: "Показать полностью",
    show_less: "Свернуть",
    too_long: "Слишком длинно: не больше {max} символов.",
    save_failed: "Заметка не сохранена: {error}",
    load_failed: "Не удалось загрузить заметки: {error}",
    panel_title: "Заметки",
    menu: "Меню",
    search: "Поиск по заметкам",
    clear_search: "Очистить поиск",
    total: "Всего заметок: {count}",
    empty: "Заметок пока нет. Откройте сущность и добавьте заметку под её элементами управления.",
    no_results: "По запросу «{query}» ничего не найдено.",
    removed_section: "Заметки удалённых сущностей",
    state_deleted: "Сущность удалена. Заметки вернутся, если её добавят снова.",
    state_orphaned: "Сущности больше нет. Остались только эти заметки.",
    forget: "Удалить заметки",
    forget_title: "Удалить эти заметки?",
    forget_text: "Заметки к «{entity}» будут удалены. Отменить это нельзя.",
    open_entity: "Открыть «{entity}»",
  },
};

// ---------------------------------------------------------------- helpers

function getHass() {
  return document.querySelector("home-assistant")?.hass;
}

function languageOf(hass) {
  const language = hass?.locale?.language || hass?.language || "en";
  return language.split("-")[0] in STRINGS ? language.split("-")[0] : "en";
}

function translate(hass, key, values = {}) {
  const text = STRINGS[languageOf(hass)][key] ?? STRINGS.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (match, name) =>
    name in values ? String(values[name]) : match,
  );
}

function isAdmin(hass) {
  return Boolean(hass?.user?.is_admin);
}

function entityName(hass, entityId) {
  return hass?.states?.[entityId]?.attributes?.friendly_name || entityId;
}

function truncate(text, length) {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function errorText(error) {
  return error?.message || error?.code || String(error);
}

/** Build an element. `.prop` sets a property, `onX` adds a listener, the rest are attributes. */
function h(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) {
      continue;
    }
    if (key.startsWith(".")) {
      element[key.slice(1)] = value;
    } else if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2), value);
    } else {
      element.setAttribute(key, value === true ? "" : String(value));
    }
  }
  appendChildren(element, children);
  return element;
}

function appendChildren(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) {
      continue;
    }
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

function svgIcon(path, className = "icon") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS(ns, "path");
  shape.setAttribute("d", path);
  svg.append(shape);
  return svg;
}

/** HA's ha-button when defined (it is in the main bundle), else a plain button. */
function button(label, { onClick, variant, appearance = "plain", iconPath, size = "s" } = {}) {
  if (customElements.get("ha-button")) {
    return h(
      "ha-button",
      { appearance, variant, size, onclick: onClick },
      iconPath ? h("span", { slot: "start", class: "button-icon" }, svgIcon(iconPath)) : null,
      label,
    );
  }
  return h(
    "button",
    { class: `fallback-button ${appearance} ${variant || ""}`, type: "button", onclick: onClick },
    iconPath ? svgIcon(iconPath, "icon small") : null,
    label,
  );
}

function fire(node, type, detail) {
  node.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
}

// ------------------------------------------------------------ hook reports

const hookState = {};
let reportTimer;

/** Remember whether a hook attached; admins' browsers report changes to Repairs. */
function reportHook(name, ok, detail = "") {
  if (hookState[name]?.ok === ok) {
    return;
  }
  hookState[name] = { ok, detail, sent: false };
  if (!ok) {
    console.warn(`[entity_note] UI hook "${name}" did not attach: ${detail}`);
  }
  clearTimeout(reportTimer);
  reportTimer = setTimeout(sendHookReport, 2000);
}

async function sendHookReport() {
  const hass = getHass();
  if (!isAdmin(hass)) {
    return;
  }
  const hooks = {};
  const details = [];
  for (const [name, state] of Object.entries(hookState)) {
    if (!state.sent) {
      hooks[name] = state.ok;
      if (!state.ok) {
        details.push(`${name}: ${state.detail}`);
      }
    }
  }
  if (!Object.keys(hooks).length) {
    return;
  }
  try {
    await hass.callWS({
      type: `${DOMAIN}/frontend_report`,
      hooks,
      detail: details.join("; ").slice(0, 500),
    });
    for (const name of Object.keys(hooks)) {
      hookState[name].sent = true;
    }
  } catch (error) {
    console.warn("[entity_note] could not report UI hooks", error);
  }
}

// ------------------------------------------------------------- shared data

/** Every note (admins only), for the Entities table and the Notes panel. */
const notesStore = {
  notes: null,
  error: null,
  version: 0,
  listeners: new Set(),
  loading: null,
  unsubscribe: null,

  listen(listener) {
    this.listeners.add(listener);
    this.ensureLoaded();
    return () => this.listeners.delete(listener);
  },

  ensureLoaded() {
    if (this.notes === null && !this.loading) {
      void this.reload();
    }
    void this.ensureSubscribed();
  },

  async ensureSubscribed() {
    const hass = getHass();
    if (this.unsubscribe || !isAdmin(hass)) {
      return;
    }
    this.unsubscribe = true;
    try {
      this.unsubscribe = await hass.connection.subscribeMessage(() => this.reload(), {
        type: `${DOMAIN}/subscribe`,
      });
    } catch (error) {
      this.unsubscribe = null;
      console.warn("[entity_note] could not subscribe to note changes", error);
    }
  },

  async reload() {
    const hass = getHass();
    if (!isAdmin(hass)) {
      return;
    }
    const loading = hass.callWS({ type: `${DOMAIN}/list` });
    this.loading = loading;
    try {
      const result = await loading;
      this.notes = result.notes;
      this.privateByEntity = new Map(
        result.notes
          .filter((row) => row.state === "active" && row.private)
          .map((row) => [row.entity_id, row.private]),
      );
      this.error = null;
    } catch (error) {
      this.error = error;
    } finally {
      if (this.loading === loading) {
        this.loading = null;
      }
    }
    this.version += 1;
    for (const listener of this.listeners) {
      listener();
    }
  },

  privateByEntity: new Map(),
};

window.addEventListener("entity-note-changed", () => {
  if (notesStore.notes !== null) {
    void notesStore.reload();
  }
});

// ------------------------------------------------------------------ styles

const NOTE_STYLES = `
  :host { display: block; }
  [hidden] { display: none !important; }
  .icon { width: 20px; height: 20px; fill: currentColor; flex: none; }
  .icon.small { width: 18px; height: 18px; }
  .button-icon { display: inline-flex; }
  .button-icon .icon { width: 18px; height: 18px; }
  .section + .section { border-top: 1px solid var(--divider-color); }
  .section { padding: var(--ha-space-3, 12px) var(--ha-space-4, 16px); }
  .heading {
    display: flex; align-items: center; gap: var(--ha-space-2, 8px);
    min-height: 32px;
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-medium, 500);
  }
  .heading .title { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .heading .icon { color: var(--secondary-text-color); }
  .private .heading { color: var(--secondary-text-color); font-weight: var(--ha-font-weight-normal, 400); }
  .heading ha-button, .heading .fallback-button { margin-inline-end: calc(-1 * var(--ha-space-3, 12px)); }
  .text {
    margin: var(--ha-space-2, 8px) 0 0;
    border: var(--ha-border-width-sm, 1px) solid var(--ha-color-border-neutral-quiet, var(--divider-color));
    padding: var(--ha-space-1, 4px) var(--ha-space-3, 12px);
    border-radius: var(--ha-border-radius-lg, 12px);
    background-color: var(--ha-color-fill-neutral-quiet-resting, var(--secondary-background-color));
    color: var(--primary-text-color);
    font-size: var(--ha-font-size-m, 14px);
    line-height: 1.5;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
  .private .text { border-style: dashed; }
  .text.clamped {
    max-height: calc(1.5em * ${CLAMP_LINES});
    overflow: hidden;
    -webkit-mask-image: linear-gradient(to bottom, #000 70%, transparent);
    mask-image: linear-gradient(to bottom, #000 70%, transparent);
  }
  .toggle { margin-top: var(--ha-space-1, 4px); }
  .actions { display: flex; flex-wrap: wrap; gap: var(--ha-space-1, 4px) var(--ha-space-2, 8px); }
  .actions.inline { padding: var(--ha-space-1, 4px) var(--ha-space-2, 8px); }
  .fallback-button {
    display: inline-flex; align-items: center; gap: 6px;
    border: none; background: none; cursor: pointer;
    color: var(--primary-color); font: inherit; font-weight: 500;
    padding: 6px 12px; border-radius: var(--ha-border-radius-pill, 999px);
  }
  .fallback-button:hover { background: var(--ha-color-fill-primary-quiet-hover, rgba(0, 0, 0, 0.05)); }
  .fallback-button.filled { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .fallback-button.danger { color: var(--error-color); }
`;

const CARD_STYLES = `
  .card {
    display: block;
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color, #e0e0e0));
    border-radius: var(--ha-card-border-radius, var(--ha-border-radius-lg, 12px));
    color: var(--primary-text-color);
    overflow: hidden;
  }
`;

// ------------------------------------------------------------- note block

/** Render one note (heading + grey box) with a "show more" toggle for long text. */
function noteSection(hass, { kind, text, onEdit }) {
  const isPrivate = kind === "private";
  const box = h("div", { class: "text" }, text);
  const toggle = h("div", { class: "toggle", hidden: true });
  const section = h(
    "section",
    {
      class: `section ${kind}`,
      "aria-label": translate(hass, isPrivate ? "private_note" : "note"),
    },
    h(
      "div",
      { class: "heading" },
      svgIcon(isPrivate ? ICONS.lock : ICONS.note),
      h("span", { class: "title" }, translate(hass, isPrivate ? "private_note" : "note")),
      onEdit ? button(translate(hass, "edit"), { onClick: onEdit }) : null,
    ),
    box,
    toggle,
  );
  // Clamp long notes once the box has a size.
  requestAnimationFrame(() => {
    box.classList.add("clamped");
    if (box.scrollHeight <= box.clientHeight + 2) {
      box.classList.remove("clamped");
      return;
    }
    let expanded = false;
    const label = () => translate(hass, expanded ? "show_less" : "show_more");
    const control = button(label(), {
      onClick: () => {
        expanded = !expanded;
        box.classList.toggle("clamped", !expanded);
        control.lastChild.textContent = label();
      },
    });
    toggle.replaceChildren(control);
    toggle.hidden = false;
  });
  return section;
}

/** Open the edit dialog through HA's dialog manager (back button closes it). */
function openNoteDialog(origin, params) {
  fire(origin, "show-dialog", {
    dialogTag: "entity-note-dialog",
    dialogImport: () => Promise.resolve(),
    dialogParams: params,
  });
}

class EntityNoteCard extends HTMLElement {
  #hass = undefined;
  #entityId = undefined;
  #entry = undefined;
  #notes = null;
  #requested = null;
  #renderKey = "";
  #onChanged;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.#onChanged = (event) => {
      if (event.detail?.entityId === this.#entityId) {
        this.#notes = event.detail.notes ?? this.#notes;
        this.#render();
        void this.#load(true);
      }
    };
  }

  connectedCallback() {
    window.addEventListener("entity-note-changed", this.#onChanged);
  }

  disconnectedCallback() {
    window.removeEventListener("entity-note-changed", this.#onChanged);
  }

  /** Called by the more-info hook after every render of the host; must stay cheap. */
  setContext(hass, entityId, entry) {
    const entityChanged = entityId !== this.#entityId;
    const entryChanged = entry !== this.#entry;
    this.#hass = hass;
    this.#entityId = entityId;
    this.#entry = entry;
    if (entityChanged) {
      this.#notes = null;
      void this.#load(true);
    } else if (entryChanged && !isAdmin(hass)) {
      void this.#load(false);
    }
    this.#render();
  }

  async #load(force) {
    const hass = this.#hass;
    const entityId = this.#entityId;
    if (!hass || !entityId) {
      return;
    }
    if (!isAdmin(hass) && this.#entry && !force) {
      // Non-admins: the dialog already fetched the registry entry with its options.
      this.#notes = { public: this.#entry.options?.[DOMAIN]?.note || null, private: null };
      this.#render();
      return;
    }
    const request = isAdmin(hass)
      ? hass.callWS({ type: `${DOMAIN}/get`, entity_id: entityId })
      : hass
          .callWS({ type: "config/entity_registry/get", entity_id: entityId })
          .then((entry) => ({ public: entry.options?.[DOMAIN]?.note || null, private: null }));
    this.#requested = request;
    try {
      const notes = await request;
      if (this.#requested === request) {
        this.#notes = notes;
      }
    } catch (error) {
      if (this.#requested === request) {
        // not_found: no registry entry (no unique ID), so no notes. Anything else: log it.
        this.#notes = { public: null, private: null, unavailable: true };
        if (error?.code !== "not_found") {
          console.warn("[entity_note] could not load notes", entityId, error);
        }
      }
    }
    this.#render();
  }

  #render() {
    const hass = this.#hass;
    const notes = this.#notes;
    const admin = isAdmin(hass);
    const key = JSON.stringify([languageOf(hass), admin, this.#entityId, notes]);
    if (key === this.#renderKey) {
      return;
    }
    this.#renderKey = key;
    const root = this.shadowRoot;
    root.replaceChildren(h("style", {}, NOTE_STYLES + CARD_STYLES + HOST_STYLES));
    if (!notes || notes.unavailable || !hass) {
      this.hidden = true;
      return;
    }
    const { public: publicText, private: privateText } = notes;
    if (!admin && !publicText) {
      this.hidden = true;
      return;
    }
    this.hidden = false;
    const edit = (kind, text) => () =>
      openNoteDialog(this, { entityId: this.#entityId, kind, note: text || "" });

    if (!publicText && !privateText) {
      // Admin, no notes yet: two quiet buttons, nothing more.
      root.append(
        h(
          "div",
          { class: "actions inline" },
          button(translate(hass, "add_note"), { iconPath: ICONS.add, onClick: edit("public") }),
          button(translate(hass, "add_private_note"), {
            iconPath: ICONS.lock,
            onClick: edit("private"),
          }),
        ),
      );
      return;
    }
    const card = h("div", { class: "card" });
    if (publicText) {
      card.append(
        noteSection(hass, {
          kind: "public",
          text: publicText,
          onEdit: admin ? edit("public", publicText) : null,
        }),
      );
    } else {
      card.append(
        h(
          "div",
          { class: "section actions" },
          button(translate(hass, "add_note"), { iconPath: ICONS.add, onClick: edit("public") }),
        ),
      );
    }
    if (admin && privateText) {
      card.append(
        noteSection(hass, {
          kind: "private",
          text: privateText,
          onEdit: edit("private", privateText),
        }),
      );
    } else if (admin) {
      card.append(
        h(
          "div",
          { class: "section actions" },
          button(translate(hass, "add_private_note"), {
            iconPath: ICONS.lock,
            onClick: edit("private"),
          }),
        ),
      );
    }
    root.append(card);
  }
}

const HOST_STYLES = `
  :host { margin-top: var(--ha-space-4, 16px); flex: none; }
  :host([hidden]) { display: none; }
  .actions.section { padding: var(--ha-space-2, 8px) var(--ha-space-2, 8px); }
`;

// -------------------------------------------------------------- the dialog

const DIALOG_STYLES = `
  .helper { margin: 0 0 var(--ha-space-3, 12px); color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); line-height: 1.5; display: flex; gap: 6px; align-items: flex-start; }
  .helper .icon { width: 16px; height: 16px; margin-top: 1px; }
  /* Same look as ha-textarea: filled field, raised label, line that turns primary on focus. */
  .field {
    position: relative; display: block;
    background-color: var(--ha-color-form-background, rgba(0, 0, 0, 0.04));
    border-radius: var(--ha-border-radius-sm, 4px) var(--ha-border-radius-sm, 4px) 0 0;
    transition: background-color 0.15s ease-in-out;
  }
  .field:hover { background-color: var(--ha-color-form-background-hover, rgba(0, 0, 0, 0.07)); }
  .field::after {
    content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 1px;
    background-color: var(--ha-color-border-neutral-loud, rgba(0, 0, 0, 0.42));
    transition: height 0.15s ease-in-out, background-color 0.15s ease-in-out;
  }
  .field:focus-within::after { height: 2px; background-color: var(--primary-color); }
  .field .label {
    display: block; padding: var(--ha-space-2, 8px) var(--ha-space-4, 16px) 0;
    font-size: var(--ha-font-size-xs, 10px); color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .field:focus-within .label { color: var(--primary-color); }
  textarea {
    box-sizing: border-box; display: block; width: 100%;
    min-height: calc(1.5em * 5); max-height: 45vh; resize: none;
    margin: 0; border: none; outline: none; background: transparent;
    padding: var(--ha-space-1, 4px) var(--ha-space-4, 16px) var(--ha-space-2, 8px);
    font-family: var(--ha-font-family-body, inherit); font-size: var(--ha-font-size-m, 14px); line-height: 1.5;
    color: var(--primary-text-color);
  }
  .meta { display: flex; justify-content: space-between; gap: 12px; margin-top: 6px; color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); }
  .counter.over { color: var(--error-color); }
  .error { display: flex; gap: 8px; align-items: flex-start; margin-top: 12px; padding: 8px 12px; border-radius: var(--ha-border-radius-md, 8px); color: var(--error-color); background: var(--ha-color-fill-danger-quiet-resting, rgba(219, 68, 55, 0.1)); overflow-wrap: anywhere; }
  .confirm-text { margin: 0; color: var(--primary-text-color); overflow-wrap: anywhere; }
  dialog.fallback { border: none; border-radius: var(--ha-dialog-border-radius, 24px); padding: 24px; width: min(560px, calc(100vw - 32px)); background: var(--ha-dialog-surface-background, var(--card-background-color, #fff)); color: var(--primary-text-color); box-sizing: border-box; }
  dialog.fallback::backdrop { background: rgba(0, 0, 0, 0.32); }
  dialog.fallback h2 { margin: 0 0 16px; font-size: var(--ha-font-size-xl, 20px); font-weight: 400; }
  dialog.fallback .footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 24px; }
`;

class EntityNoteDialog extends HTMLElement {
  #params = null;
  #saving = false;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.hass = undefined;
    // ha-dialog closes itself on Escape. Cancel the key's default action as well,
    // or the browser sends a second close request to the dialog underneath (the
    // entity dialog), which then drops out of the modal layer.
    this.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Escape" && this.shadowRoot.querySelector("ha-dialog")) {
          event.preventDefault();
        }
      },
      true,
    );
  }

  /** Called by HA's dialog manager (show-dialog event). */
  async showDialog(params) {
    this.#params = params;
    this.#saving = false;
    if (!customElements.get("ha-dialog")) {
      await Promise.race([
        customElements.whenDefined("ha-dialog"),
        new Promise((resolve) => setTimeout(resolve, 1500)),
      ]);
    }
    reportHook("dialog", Boolean(customElements.get("ha-dialog")), "ha-dialog is not defined");
    this.#render();
  }

  /** Called by the dialog manager on browser back; unsaved text is kept only by Save. */
  closeDialog() {
    this.#close();
    return true;
  }

  #close() {
    const dialog = this.shadowRoot.querySelector("ha-dialog, dialog");
    if (dialog?.tagName === "HA-DIALOG" && dialog.open) {
      dialog.open = false; // Fires "closed", which finishes below.
      return;
    }
    if (dialog?.tagName === "DIALOG" && dialog.open) {
      dialog.close();
    }
    this.#finish();
  }

  #finish() {
    if (!this.#params) {
      return;
    }
    this.#params = null;
    this.shadowRoot.replaceChildren();
    fire(this, "dialog-closed", { dialog: this.localName });
  }

  #render() {
    const hass = this.hass || getHass();
    const params = this.#params;
    const root = this.shadowRoot;
    root.replaceChildren(h("style", {}, NOTE_STYLES + DIALOG_STYLES));
    if (!params) {
      return;
    }
    const confirm = params.mode === "confirm";
    const isPrivate = params.kind === "private";
    const title = confirm
      ? params.title
      : translate(
          hass,
          params.note
            ? isPrivate
              ? "edit_private_note"
              : "edit_note"
            : isPrivate
              ? "add_private_note"
              : "add_note",
        );
    const subtitle = confirm ? null : entityName(hass, params.entityId);

    const error = h("div", { class: "error", role: "alert", hidden: true });
    let textarea = null;
    let counter = null;
    let body;
    // Sizes the text box once the dialog is laid out (it has no size before).
    let settle = null;
    if (confirm) {
      body = [h("p", { class: "confirm-text" }, params.text), error];
    } else {
      textarea = h("textarea", {
        ".value": params.note,
        "aria-label": translate(hass, isPrivate ? "private_note" : "note"),
        maxlength: MAX_LENGTH,
        rows: 5,
      });
      counter = h("span", { class: "counter" });
      const updateCounter = () => {
        const length = textarea.value.length;
        counter.textContent = length > MAX_LENGTH * 0.9 ? `${length} / ${MAX_LENGTH}` : "";
        counter.classList.toggle("over", length > MAX_LENGTH);
        textarea.style.height = "auto";
        textarea.style.height = `${textarea.scrollHeight + 2}px`;
        const container = root.querySelector("ha-dialog");
        if (container) {
          container.preventScrimClose = textarea.value !== params.note;
        }
      };
      textarea.addEventListener("input", updateCounter);
      textarea.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          void this.#save(textarea.value, error);
        }
      });
      settle = () => {
        updateCounter();
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
      };
      body = [
        h(
          "p",
          { class: "helper" },
          svgIcon(isPrivate ? ICONS.lock : ICONS.note),
          h(
            "span",
            {},
            translate(hass, isPrivate ? "private_helper" : "public_helper"),
            params.note ? ` ${translate(hass, "empty_removes")}` : "",
          ),
        ),
        h(
          "label",
          { class: "field" },
          h("span", { class: "label" }, translate(hass, isPrivate ? "private_note" : "note")),
          textarea,
        ),
        h("div", { class: "meta" }, h("span"), counter),
        error,
      ];
    }

    const cancel = button(translate(hass, "cancel"), { onClick: () => this.#close() });
    const primary = confirm
      ? button(translate(hass, "delete"), {
          appearance: "accent",
          variant: "danger",
          size: "m",
          onClick: () => this.#confirm(error),
        })
      : button(translate(hass, "save"), {
          appearance: "accent",
          size: "m",
          onClick: () => this.#save(textarea.value, error),
        });
    cancel.setAttribute("size", "m");

    if (customElements.get("ha-dialog")) {
      cancel.slot = "secondaryAction";
      primary.slot = "primaryAction";
      const dialog = h(
        "ha-dialog",
        {
          "header-title": title,
          "header-subtitle": subtitle,
          type: confirm ? "alert" : "standard",
          width: "medium",
          onclosed: () => this.#finish(),
          "onafter-show": () => settle?.(),
        },
        h("div", {}, body),
        customElements.get("ha-dialog-footer")
          ? h("ha-dialog-footer", { slot: "footer" }, cancel, primary)
          : h("div", { slot: "footer", class: "footer" }, cancel, primary),
      );
      root.append(dialog);
      requestAnimationFrame(() => {
        dialog.open = true;
      });
      return;
    }
    const dialog = h(
      "dialog",
      { class: "fallback", "aria-label": title, onclose: () => this.#finish() },
      h("h2", {}, title),
      subtitle ? h("p", { class: "helper" }, subtitle) : null,
      body,
      h("div", { class: "footer" }, cancel, primary),
    );
    root.append(dialog);
    dialog.showModal();
    settle?.();
  }

  #setBusy(busy) {
    this.#saving = busy;
    for (const element of this.shadowRoot.querySelectorAll("ha-button, button")) {
      if ("loading" in element && element.getAttribute("slot") === "primaryAction") {
        element.loading = busy;
      }
      element.disabled = busy;
    }
  }

  async #save(text, errorBox) {
    const params = this.#params;
    const hass = this.hass || getHass();
    if (!params || this.#saving) {
      return;
    }
    if (text.length > MAX_LENGTH) {
      this.#showError(errorBox, translate(hass, "too_long", { max: MAX_LENGTH }));
      return;
    }
    this.#setBusy(true);
    try {
      const notes = await hass.callWS({
        type: `${DOMAIN}/update`,
        entity_id: params.entityId,
        [params.kind]: text.trim() ? text : null,
      });
      window.dispatchEvent(
        new CustomEvent("entity-note-changed", { detail: { entityId: params.entityId, notes } }),
      );
      this.#close();
    } catch (error) {
      this.#setBusy(false);
      this.#showError(errorBox, translate(hass, "save_failed", { error: errorText(error) }));
    }
  }

  async #confirm(errorBox) {
    const params = this.#params;
    if (!params || this.#saving) {
      return;
    }
    this.#setBusy(true);
    try {
      await params.action();
      this.#close();
    } catch (error) {
      this.#setBusy(false);
      this.#showError(errorBox, errorText(error));
    }
  }

  #showError(errorBox, message) {
    errorBox.replaceChildren(svgIcon(ICONS.alert, "icon small"), h("span", {}, message));
    errorBox.hidden = false;
  }
}

// ---------------------------------------------------- Settings > Entities

class EntityNoteIndicator extends HTMLElement {
  #kind = "public";
  #note = "";

  set kind(value) {
    this.#kind = value;
    this.#render();
  }

  set note(value) {
    this.#note = value;
    this.#render();
  }

  #render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    const hass = getHass();
    const label = translate(hass, this.#kind === "private" ? "private_note" : "note");
    this.title = `${label}: ${truncate(this.#note || "", TOOLTIP_LENGTH)}`;
    this.setAttribute("role", "img");
    this.setAttribute("aria-label", label);
    this.shadowRoot.replaceChildren(
      h(
        "style",
        {},
        `:host { display: inline-flex; vertical-align: middle; margin-inline-start: 6px; color: var(--secondary-text-color); }
         .icon { width: 16px; height: 16px; fill: currentColor; }`,
      ),
      svgIcon(this.#kind === "private" ? ICONS.lock : ICONS.note),
    );
  }
}

const tableInstances = new Set();
const wrappedTables = new WeakSet();
const patchedPrototypes = new WeakSet();
const moreInfoCards = new WeakMap();

function addNoteFields(row, privateNotes) {
  const publicText = row.options?.[DOMAIN]?.note || null;
  const privateText = privateNotes.get(row.entity_id) || null;
  if (!publicText && !privateText) {
    return row;
  }
  return {
    ...row,
    entity_note: [publicText, privateText].filter(Boolean).join("\n"),
    entity_note_kind: publicText ? "public" : "private",
  };
}

function addNoteColumns(host, columns) {
  const result = { ...columns };
  const name = columns.name;
  if (!name) {
    reportHook("entities_table", false, "the name column is missing");
    return columns;
  }
  const extra = name.extraTemplate;
  result.name = {
    ...name,
    extraTemplate: (row) => {
      const rest = extra ? extra(row) : "";
      if (!row.entity_note_kind) {
        return rest;
      }
      return host.html`<entity-note-indicator .kind=${row.entity_note_kind} .note=${row.entity_note}></entity-note-indicator>${rest}`;
    },
  };
  result.entity_note = {
    title: translate(getHass(), "note"),
    hidden: true,
    filterable: true,
  };
  return result;
}

function wrapEntitiesTable(host) {
  if (wrappedTables.has(host)) {
    return;
  }
  wrappedTables.add(host);
  // These two are ha-config-entities' own (TypeScript-private) members: the hook point.
  // oxlint-disable-next-line no-underscore-dangle
  const rows = host._filteredEntitiesAndDomains;
  // oxlint-disable-next-line no-underscore-dangle
  const columns = host._columns;
  if (
    typeof rows !== "function" ||
    typeof columns !== "function" ||
    typeof host.html !== "function"
  ) {
    reportHook("entities_table", false, "ha-config-entities internals changed");
    return;
  }
  tableInstances.add(host);
  let lastInput = null;
  let lastVersion = -1;
  let lastOutput = null;
  // oxlint-disable-next-line no-underscore-dangle
  host._filteredEntitiesAndDomains = (...args) => {
    const result = rows(...args);
    if (!Array.isArray(result?.filteredEntities)) {
      reportHook("entities_table", false, "unexpected row data");
      return result;
    }
    if (result !== lastInput || lastVersion !== notesStore.version) {
      lastInput = result;
      lastVersion = notesStore.version;
      const privateNotes = isAdmin(getHass()) ? notesStore.privateByEntity : new Map();
      lastOutput = {
        ...result,
        filteredEntities: result.filteredEntities.map((row) => addNoteFields(row, privateNotes)),
      };
    }
    return lastOutput;
  };
  const columnCache = new WeakMap();
  // oxlint-disable-next-line no-underscore-dangle
  host._columns = (...args) => {
    const original = columns(...args);
    let augmented = columnCache.get(original);
    if (!augmented) {
      augmented = addNoteColumns(host, original);
      columnCache.set(original, augmented);
    }
    return augmented;
  };
  reportHook("entities_table", true);
  // The first render may have happened before the patch.
  queueMicrotask(() => host.requestUpdate());
  notesStore.listen(() => {
    for (const table of tableInstances) {
      if (table.isConnected) {
        table.requestUpdate();
      } else {
        tableInstances.delete(table);
      }
    }
  });
}

function patchEntitiesTable(elementClass) {
  const proto = elementClass.prototype;
  if (patchedPrototypes.has(proto)) {
    return;
  }
  patchedPrototypes.add(proto);
  const original = proto.willUpdate;
  proto.willUpdate = function willUpdate(changed) {
    try {
      wrapEntitiesTable(this);
    } catch (error) {
      reportHook("entities_table", false, errorText(error));
    }
    return original?.call(this, changed);
  };
}

// ------------------------------------------------------ the entity dialog

function attachToMoreInfo(host) {
  if (!host.hass || !host.entityId) {
    return;
  }
  const content = host.shadowRoot?.querySelector(".container > .content");
  if (!content) {
    reportHook("more_info", false, "ha-more-info-info has no .content");
    return;
  }
  let card = moreInfoCards.get(host);
  if (!card) {
    card = document.createElement("entity-note-card");
    moreInfoCards.set(host, card);
  }
  // Last child of the content column, after the controls. Lit only replaces nodes
  // inside its own parts, all of which sit before more-info-content.
  if (card.parentNode !== content || content.lastElementChild !== card) {
    content.append(card);
  }
  card.setContext(host.hass, host.entityId, host.entry);
  reportHook("more_info", true);
}

function patchMoreInfo(elementClass) {
  const proto = elementClass.prototype;
  if (patchedPrototypes.has(proto)) {
    return;
  }
  patchedPrototypes.add(proto);
  const original = proto.updated;
  proto.updated = function updated(changed) {
    original?.call(this, changed);
    try {
      attachToMoreInfo(this);
    } catch (error) {
      reportHook("more_info", false, errorText(error));
    }
  };
}

// ---------------------------------------------------------- the Notes panel

const PANEL_STYLES = `
  :host { display: block; height: 100%; background: var(--primary-background-color); color: var(--primary-text-color); font-family: var(--ha-font-family-body, Roboto, sans-serif); -webkit-font-smoothing: antialiased; }
  .toolbar {
    display: flex; align-items: center; gap: 4px; box-sizing: border-box;
    height: var(--header-height, 56px); padding: 0 12px;
    padding-top: var(--safe-area-inset-top, 0px);
    background: var(--app-header-background-color, var(--primary-background-color));
    color: var(--app-header-text-color, var(--primary-text-color));
    border-bottom: var(--app-header-border-bottom, 1px solid var(--divider-color));
    position: sticky; top: 0; z-index: 2;
  }
  .toolbar .title { font-size: var(--ha-font-size-xl, 20px); font-weight: var(--ha-font-weight-normal, 400); margin-inline-start: 12px; flex: 1; }
  .icon-button { display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; border: none; border-radius: 50%; background: none; color: inherit; cursor: pointer; }
  .icon-button:hover { background: var(--ha-color-fill-neutral-quiet-hover, rgba(127, 127, 127, 0.12)); }
  .icon-button .icon { width: 24px; height: 24px; fill: currentColor; }
  main { box-sizing: border-box; max-width: 1040px; margin: 0 auto; padding: var(--ha-space-4, 16px); padding-bottom: calc(var(--ha-space-6, 24px) + var(--safe-area-inset-bottom, 0px)); }
  .search { display: flex; align-items: center; gap: 8px; height: 48px; padding: 0 8px 0 16px; box-sizing: border-box; border: 1px solid var(--divider-color); border-radius: var(--ha-border-radius-pill, 24px); background: var(--card-background-color); color: var(--secondary-text-color); }
  .search:focus-within { border-color: var(--primary-color); box-shadow: inset 0 0 0 1px var(--primary-color); }
  .search input { flex: 1; min-width: 0; border: none; outline: none; background: none; font: inherit; font-size: var(--ha-font-size-m, 14px); color: var(--primary-text-color); }
  .search .icon-button { width: 36px; height: 36px; }
  .summary { margin: 12px 4px 8px; color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); }
  .list { display: grid; gap: 12px; }
  h2 { font-size: var(--ha-font-size-l, 16px); font-weight: var(--ha-font-weight-medium, 500); margin: 28px 4px 4px; }
  .removed-hint { margin: 0 4px 12px; color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); }
  .entity { display: flex; align-items: center; gap: 12px; width: 100%; box-sizing: border-box; padding: 12px 16px 4px; border: none; background: none; color: inherit; font: inherit; text-align: start; }
  button.entity { cursor: pointer; }
  button.entity:hover .name { color: var(--primary-color); }
  .entity .names { flex: 1; min-width: 0; }
  .entity .name { font-weight: var(--ha-font-weight-medium, 500); font-size: var(--ha-font-size-m, 14px); overflow-wrap: anywhere; }
  .entity .id { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); overflow-wrap: anywhere; }
  .badge { display: inline-block; margin: 0 16px; padding: 2px 8px; border-radius: 999px; font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); background: var(--ha-color-fill-neutral-quiet-resting, var(--secondary-background-color)); }
  .card .section { padding-top: 8px; padding-bottom: 8px; }
  .card .forget { display: flex; justify-content: flex-end; padding: 0 8px 8px; }
  mark { background: var(--ha-color-fill-warning-quiet-resting, rgba(255, 193, 7, 0.35)); color: inherit; border-radius: 2px; }
  .empty { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 48px 16px; color: var(--secondary-text-color); text-align: center; }
  .empty .icon { width: 48px; height: 48px; fill: currentColor; opacity: 0.6; }
  .load-error { margin-top: 16px; }
`;

function normalizeSearch(text) {
  return (text || "")
    .toLocaleLowerCase()
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "");
}

class EntityNotePanel extends HTMLElement {
  #hass = undefined;
  #narrow = false;
  #query = "";
  #language = null;
  #unlisten = null;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = !this.#hass;
    this.#hass = hass;
    if (first || languageOf(hass) !== this.#language) {
      this.#build();
    }
  }

  get hass() {
    return this.#hass;
  }

  set narrow(narrow) {
    this.#narrow = narrow;
    const menu = this.shadowRoot.querySelector(".menu");
    if (menu) {
      menu.hidden = !narrow;
    }
  }

  set panel(_panel) {}

  set route(_route) {}

  connectedCallback() {
    this.#unlisten = notesStore.listen(() => this.#renderList());
  }

  disconnectedCallback() {
    this.#unlisten?.();
    this.#unlisten = null;
  }

  #build() {
    const hass = this.#hass;
    this.#language = languageOf(hass);
    const input = h("input", {
      type: "search",
      ".value": this.#query,
      placeholder: translate(hass, "search"),
      "aria-label": translate(hass, "search"),
      oninput: (event) => {
        this.#query = event.target.value;
        clear.hidden = !this.#query;
        this.#renderList();
      },
    });
    const clear = h(
      "button",
      {
        class: "icon-button",
        type: "button",
        title: translate(hass, "clear_search"),
        "aria-label": translate(hass, "clear_search"),
        hidden: !this.#query,
        onclick: () => {
          this.#query = "";
          input.value = "";
          clear.hidden = true;
          this.#renderList();
          input.focus();
        },
      },
      svgIcon(ICONS.close),
    );
    this.shadowRoot.replaceChildren(
      h("style", {}, NOTE_STYLES + CARD_STYLES + PANEL_STYLES),
      h(
        "div",
        { class: "toolbar" },
        h(
          "button",
          {
            class: "icon-button menu",
            type: "button",
            hidden: !this.#narrow,
            title: translate(hass, "menu"),
            "aria-label": translate(hass, "menu"),
            onclick: () => fire(this, "hass-toggle-menu"),
          },
          svgIcon(ICONS.menu),
        ),
        h("div", { class: "title" }, translate(hass, "panel_title")),
      ),
      h(
        "main",
        {},
        h("label", { class: "search" }, svgIcon(ICONS.search, "icon"), input, clear),
        h("div", { class: "results" }),
      ),
    );
    this.#renderList();
  }

  #renderList() {
    const results = this.shadowRoot.querySelector(".results");
    const hass = this.#hass;
    if (!results || !hass) {
      return;
    }
    if (notesStore.error) {
      results.replaceChildren(
        h(
          "div",
          { class: "load-error error", role: "alert" },
          svgIcon(ICONS.alert, "icon small"),
          translate(hass, "load_failed", { error: errorText(notesStore.error) }),
        ),
      );
      return;
    }
    if (notesStore.notes === null) {
      results.replaceChildren();
      return;
    }
    const rows = notesStore.notes
      .map((row) => ({ ...row, name: entityName(hass, row.entity_id) }))
      .toSorted((a, b) => a.name.localeCompare(b.name, languageOf(hass)));
    const terms = normalizeSearch(this.#query).split(/\s+/).filter(Boolean);
    const matching = rows.filter((row) => {
      const haystack = normalizeSearch(
        [row.name, row.entity_id, row.public, row.private].filter(Boolean).join("\n"),
      );
      return terms.every((term) => haystack.includes(term));
    });
    if (!rows.length) {
      results.replaceChildren(
        h("div", { class: "empty" }, svgIcon(ICONS.empty), h("div", {}, translate(hass, "empty"))),
      );
      return;
    }
    const active = matching.filter((row) => row.state === "active");
    const removed = matching.filter((row) => row.state !== "active");
    const parts = [
      h("div", { class: "summary" }, translate(hass, "total", { count: matching.length })),
    ];
    if (!matching.length) {
      parts.push(
        h("div", { class: "empty" }, translate(hass, "no_results", { query: this.#query })),
      );
    }
    if (active.length) {
      parts.push(
        h(
          "div",
          { class: "list" },
          active.map((row) => this.#noteCard(row)),
        ),
      );
    }
    if (removed.length) {
      parts.push(
        h("h2", {}, translate(hass, "removed_section")),
        h(
          "div",
          { class: "list" },
          removed.map((row) => this.#noteCard(row)),
        ),
      );
    }
    results.replaceChildren(...parts);
  }

  #noteCard(row) {
    const hass = this.#hass;
    const active = row.state === "active";
    const heading = [
      h(
        "div",
        { class: "names" },
        h("div", { class: "name" }, row.name),
        row.name !== row.entity_id ? h("div", { class: "id" }, row.entity_id) : null,
      ),
    ];
    const header = active
      ? h(
          "button",
          {
            class: "entity",
            type: "button",
            title: translate(hass, "open_entity", { entity: row.name }),
            onclick: () => fire(this, "hass-more-info", { entityId: row.entity_id }),
          },
          heading,
        )
      : h("div", { class: "entity" }, heading);
    const card = h("div", { class: "card" }, header);
    if (!active) {
      card.append(
        h(
          "span",
          { class: "badge" },
          translate(hass, row.state === "deleted" ? "state_deleted" : "state_orphaned"),
        ),
      );
    }
    const editFor = (kind, text) =>
      active
        ? () => openNoteDialog(this, { entityId: row.entity_id, kind, note: text || "" })
        : null;
    if (row.public) {
      card.append(
        noteSection(hass, {
          kind: "public",
          text: row.public,
          onEdit: editFor("public", row.public),
        }),
      );
    }
    if (row.private) {
      card.append(
        noteSection(hass, {
          kind: "private",
          text: row.private,
          onEdit: editFor("private", row.private),
        }),
      );
    }
    if (!active) {
      card.append(
        h(
          "div",
          { class: "forget" },
          button(translate(hass, "forget"), {
            variant: "danger",
            onClick: () =>
              openNoteDialog(this, {
                mode: "confirm",
                title: translate(hass, "forget_title"),
                text: translate(hass, "forget_text", { entity: row.entity_id }),
                action: async () => {
                  await getHass().callWS({
                    type: `${DOMAIN}/forget`,
                    registry_id: row.registry_id,
                  });
                  await notesStore.reload();
                },
              }),
          }),
        ),
      );
    }
    this.#highlight(card);
    return card;
  }

  /** Mark search terms inside the rendered text nodes (text stays text). */
  #highlight(root) {
    const terms = this.#query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) {
      return;
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) {
      if (!walker.currentNode.parentElement.closest("ha-button, button:not(.entity)")) {
        nodes.push(walker.currentNode);
      }
    }
    for (const node of nodes) {
      const text = node.textContent;
      const lower = text.toLocaleLowerCase();
      const ranges = [];
      for (const term of terms) {
        let index = lower.indexOf(term);
        while (index !== -1) {
          ranges.push([index, index + term.length]);
          index = lower.indexOf(term, index + term.length);
        }
      }
      if (!ranges.length) {
        continue;
      }
      const fragment = document.createDocumentFragment();
      let position = 0;
      for (const [start, end] of ranges.toSorted((a, b) => a[0] - b[0])) {
        if (start < position) {
          continue;
        }
        fragment.append(text.slice(position, start), h("mark", {}, text.slice(start, end)));
        position = end;
      }
      fragment.append(text.slice(position));
      node.replaceWith(fragment);
    }
  }
}

// ------------------------------------------------------------------- start

function define(name, elementClass) {
  if (!customElements.get(name)) {
    customElements.define(name, elementClass);
  }
}

define("entity-note-card", EntityNoteCard);
define("entity-note-dialog", EntityNoteDialog);
define("entity-note-indicator", EntityNoteIndicator);
define("entity-note-panel", EntityNotePanel);

function whenDefined(name, timeout) {
  return Promise.race([
    customElements.whenDefined(name).then(() => customElements.get(name)),
    new Promise((resolve) => setTimeout(() => resolve(null), timeout)),
  ]);
}

// The more-info chunk loads right after the first render, so give it a minute.
void whenDefined("ha-more-info-info", 60000).then((elementClass) => {
  if (!elementClass) {
    reportHook("more_info", false, "ha-more-info-info is not defined");
    return;
  }
  if (typeof elementClass.prototype.updated !== "function") {
    reportHook("more_info", false, "ha-more-info-info has no updated()");
    return;
  }
  patchMoreInfo(elementClass);
});

// The Entities page loads on demand: patch it whenever it gets defined.
void customElements.whenDefined("ha-config-entities").then(() => {
  const elementClass = customElements.get("ha-config-entities");
  if (typeof elementClass?.prototype?.willUpdate !== "function") {
    reportHook("entities_table", false, "ha-config-entities has no willUpdate()");
    return;
  }
  patchEntitiesTable(elementClass);
});
