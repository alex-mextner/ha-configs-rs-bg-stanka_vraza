/* Network devices: router-cli inventory through authenticated HA services (rest_command.network_*).
 * The inventory is fetched over the HA websocket with return_response — never via /local.
 * Everything coming from devices (hostnames, page titles, vendors) is rendered with textContent only.
 *
 * Config: title, default_filter (recent|active|all|pinned|new|unknown), refresh_interval (s, default 60),
 *         recent_hours (24), new_hours (24), dry_run (bool: pin/unpin pass --dry-run to router-cli).
 */
const ND_FILTERS = [
  ['recent', 'Недавние'], ['active', 'Онлайн'], ['all', 'Все'],
  ['pinned', 'Закреплённые'], ['new', 'Новые'], ['unknown', 'Неизвестный вендор'],
];
const ND_SORTS = [['last_seen', 'По активности'], ['name', 'По имени'], ['ip', 'По IP']];
const ND_MDI = /^mdi:[a-z0-9-]{1,64}$/;
const ND_ICON_RULES = [
  [/iphone|android|galaxy|pixel|redmi|xiaomi.*phone|oneplus|honor|huawei.*p\d|смартфон|телефон/i, 'mdi:cellphone'],
  [/ipad|tablet|tab[ -]?s\d|планшет/i, 'mdi:tablet'],
  [/macbook|laptop|notebook|thinkpad|probook|elitebook|ноутбук/i, 'mdi:laptop'],
  [/desktop|imac|mac-?mini|-pc\b|\bpc\b|workstation/i, 'mdi:desktop-tower-monitor'],
  [/home ?assistant|\bhass\b/i, 'mdi:home-assistant'],
  [/router|gateway|ubee|keenetic|mikrotik|tp-?link|asus.*rt|роутер/i, 'mdi:router-network'],
  [/tv|bravia|webos|tizen|android ?tv|chromecast|телевизор/i, 'mdi:television'],
  [/yandex|станци|station|alexa|echo|homepod|nest ?(mini|audio)|speaker|sonos/i, 'mdi:speaker'],
  [/printer|laserjet|deskjet|epson|brother|canon|kyocera|принтер/i, 'mdi:printer'],
  [/k1|creality|snapmaker|prusa|bambu|klipper|octoprint|fluidd|mainsail|3d/i, 'mdi:printer-3d'],
  [/camera|cam\b|ipc|hikvision|dahua|reolink|камера/i, 'mdi:cctv'],
  [/playstation|xbox|nintendo|switch|steam ?deck/i, 'mdi:gamepad-variant'],
  [/watch|band|часы/i, 'mdi:watch'],
  [/vacuum|roborock|dreame|пылесос/i, 'mdi:robot-vacuum'],
  [/esp|espressif|tuya|shelly|sonoff|tasmota|zigbee|bridge/i, 'mdi:chip'],
  [/nas|synology|qnap/i, 'mdi:nas'],
];

class NetworkDevicesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this._data = null; this._error = ''; this._busy = false; this._loadedAt = 0; this._seq = 0;
    this._filter = null; this._query = ''; this._sort = 'last_seen';
    this._confirm = null;   // mac with an open pin/unpin confirmation: {mac, action}
    this._editing = null;   // mac with an open rename/icon editor
    this._pending = new Set(); // macs with an action in flight
    this._visibility = () => { if (!document.hidden && Date.now() - this._loadedAt > 15000) this._load(); };
  }

  setConfig(config) {
    this._config = {refresh_interval: 60, recent_hours: 24, new_hours: 24, ...(config || {})};
    if (this._filter === null) {
      const f = this._config.default_filter;
      this._filter = ND_FILTERS.some(([k]) => k === f) ? f : 'recent';
    }
    if (this._built) this._render();
  }
  set hass(value) {
    const first = !this._hass; this._hass = value;
    if (first && this.isConnected) this._start();
  }
  getCardSize() { return 10; }
  getGridOptions() { return {columns: 'full', rows: 'auto'}; }
  connectedCallback() { if (!this._built) this._build(); this._start(); }
  disconnectedCallback() {
    clearInterval(this._timer); this._timer = null; clearTimeout(this._scanTimer);
    document.removeEventListener('visibilitychange', this._visibility);
  }

  _start() {
    if (this._timer || !this._hass || !this.isConnected) return;
    if (!this._built) this._build();
    document.addEventListener('visibilitychange', this._visibility);
    const every = Math.max(15, Number(this._config?.refresh_interval) || 60) * 1000;
    this._timer = setInterval(() => { if (!document.hidden) this._load(); }, every);
    this._load();
  }

  _node(tag, text, parent, cls) {
    const e = document.createElement(tag);
    if (text !== null && text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    if (parent) parent.append(e);
    return e;
  }
  _icon(name, parent, cls) {
    const i = document.createElement('ha-icon');
    i.setAttribute('icon', ND_MDI.test(name || '') ? name : 'mdi:help-circle-outline');
    if (cls) i.className = cls;
    if (parent) parent.append(i);
    return i;
  }
  _button(label, icon, parent, cls, onClick) {
    const b = this._node('button', null, parent, cls);
    b.type = 'button';
    if (icon) this._icon(icon, b);
    if (label) this._node('span', label, b);
    b.addEventListener('click', ev => { ev.stopPropagation(); onClick(ev); });
    return b;
  }

  _build() {
    this._built = true;
    this._node('style', `
      :host{display:block}
      ha-card{padding:16px 16px 8px;overflow:hidden}
      .head{display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap}
      .head h2{margin:0;font-size:20px;font-weight:600;line-height:1.3}
      .titlebox{flex:1;min-width:200px}
      .muted{color:var(--secondary-text-color);font-size:13px;line-height:1.5}
      .test{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:500;
        background:var(--warning-color,#ff9800);color:#fff;vertical-align:middle}
      .headbtns{display:flex;gap:6px}
      button{font:inherit;font-size:13px;min-height:36px;padding:4px 10px;border-radius:18px;cursor:pointer;
        border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);
        display:inline-flex;align-items:center;gap:6px}
      button ha-icon{--mdc-icon-size:18px}
      button:hover{background:var(--secondary-background-color)}
      button:disabled{opacity:.5;cursor:default}
      button.primary{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:transparent}
      button.danger{color:var(--error-color)}
      button.icon{padding:4px 8px}
      .spin ha-icon{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
      .chips{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 10px}
      .chip{min-height:32px;border-radius:16px;padding:2px 12px}
      .chip .n{color:var(--secondary-text-color);font-size:12px}
      .chip[aria-pressed=true]{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:transparent}
      .chip[aria-pressed=true] .n{color:inherit;opacity:.85}
      .tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px}
      input,select{font:inherit;font-size:14px;min-height:36px;box-sizing:border-box;padding:4px 10px;border-radius:8px;
        border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
      input.search{flex:1;min-width:180px}
      .error{color:var(--error-color);font-size:14px;margin:8px 0}
      .list{display:flex;flex-direction:column}
      .row{display:grid;grid-template-columns:44px minmax(0,1fr) auto;gap:4px 12px;padding:10px 4px;
        border-top:1px solid var(--divider-color);align-items:start}
      .row.offline .avatar ha-icon{opacity:.45}
      .avatar{position:relative;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;
        background:var(--secondary-background-color);color:var(--state-icon-color,var(--primary-color))}
      .avatar ha-icon{--mdc-icon-size:24px}
      .dot{position:absolute;right:0;bottom:0;width:11px;height:11px;border-radius:50%;
        border:2px solid var(--card-background-color);background:var(--disabled-text-color,#9e9e9e)}
      .dot.on{background:var(--success-color,#43a047)}
      .main{min-width:0}
      .name{font-size:15px;font-weight:600;line-height:1.35;overflow-wrap:anywhere}
      .line{font-size:13px;line-height:1.5;color:var(--secondary-text-color);display:flex;flex-wrap:wrap;align-items:center;gap:2px 10px}
      .mono{font-family:var(--code-font-family,monospace);font-size:12.5px}
      .ip{color:var(--primary-text-color);font-size:13.5px}
      .badge{display:inline-flex;align-items:center;gap:3px;padding:0 7px;border-radius:9px;font-size:11.5px;line-height:18px;
        background:var(--secondary-background-color);color:var(--secondary-text-color)}
      .badge ha-icon{--mdc-icon-size:13px}
      .badge.pin{background:rgba(var(--rgb-primary-color,3,169,244),.15);color:var(--primary-color)}
      .badge.warn{background:rgba(var(--rgb-warning-color,255,152,0),.18);color:var(--warning-color,#ff9800)}
      .badge.new{background:rgba(var(--rgb-success-color,67,160,71),.18);color:var(--success-color,#43a047)}
      .line ha-icon.if{--mdc-icon-size:15px}
      .svcs{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
      a.svc{display:inline-flex;align-items:center;gap:6px;max-width:100%;padding:3px 10px 3px 6px;border-radius:14px;
        border:1px solid var(--divider-color);color:var(--primary-text-color);text-decoration:none;font-size:12.5px;line-height:20px}
      a.svc:hover{background:var(--secondary-background-color);border-color:var(--primary-color)}
      a.svc img,a.svc ha-icon{width:16px;height:16px;--mdc-icon-size:16px;flex:none;border-radius:3px}
      a.svc .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px}
      a.svc .p{color:var(--secondary-text-color);font-family:var(--code-font-family,monospace);font-size:11.5px}
      .acts{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
      .panel{grid-column:2 / -1;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 10px;margin-top:4px;
        border-radius:10px;background:var(--secondary-background-color);font-size:13px}
      .panel input{min-width:140px;flex:1}
      .panel .preview{--mdc-icon-size:22px}
      .empty{padding:24px 4px;text-align:center;color:var(--secondary-text-color)}
      .foot{padding:8px 4px 4px;font-size:12px;color:var(--secondary-text-color)}
      :focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}
      @media(max-width:600px){
        ha-card{padding:12px 12px 6px}
        .row{grid-template-columns:40px minmax(0,1fr)}
        .acts{grid-column:2 / -1;justify-content:flex-start}
        .panel{grid-column:1 / -1}
        a.svc .t{max-width:160px}
      }
    `, this.shadowRoot);
    const card = this._node('ha-card', null, this.shadowRoot);
    const head = this._node('div', null, card, 'head');
    const tb = this._node('div', null, head, 'titlebox');
    this._title = this._node('h2', null, tb);
    this._summary = this._node('div', 'Загрузка…', tb, 'muted');
    this._summary.setAttribute('role', 'status');
    const hb = this._node('div', null, head, 'headbtns');
    this._scanBtn = this._button('Сканировать', 'mdi:radar', hb, '', () => this._scan(null));
    this._scanBtn.title = 'Проверить веб-интерфейсы всех онлайн-устройств';
    this._refreshBtn = this._button('', 'mdi:refresh', hb, 'icon', () => this._load());
    this._refreshBtn.title = 'Обновить'; this._refreshBtn.setAttribute('aria-label', 'Обновить');
    this._chips = this._node('div', null, card, 'chips');
    this._chips.setAttribute('role', 'toolbar');
    const tools = this._node('div', null, card, 'tools');
    this._search = this._node('input', null, tools, 'search');
    this._search.type = 'search'; this._search.placeholder = 'Поиск: имя, IP, MAC, вендор…';
    this._search.setAttribute('aria-label', 'Поиск устройств');
    this._search.addEventListener('input', () => { this._query = this._search.value.trim().toLowerCase(); this._renderList(); });
    this._sortSel = this._node('select', null, tools);
    this._sortSel.setAttribute('aria-label', 'Сортировка');
    for (const [k, label] of ND_SORTS) { const o = this._node('option', label, this._sortSel); o.value = k; }
    this._sortSel.addEventListener('change', () => { this._sort = this._sortSel.value; this._renderList(); });
    this._err = this._node('div', '', card, 'error');
    this._list = this._node('div', null, card, 'list');
    this._foot = this._node('div', '', card, 'foot');
    this._render();
  }

  /* ---------- data ---------- */
  async _service(service, service_data = {}) {
    const result = await this._hass.callWS({type: 'call_service', domain: 'rest_command', service,
      service_data, return_response: true});
    const response = result?.response;
    const content = response?.content;
    if (!response || response.status !== 200 || !content || content.ok === false) {
      const code = (content && typeof content === 'object' && content.error) || `HTTP ${response?.status ?? '?'}`;
      throw new Error(String(code));
    }
    return content;
  }

  async _load() {
    if (!this._hass) return;
    if (this._busy) { this._reloadWanted = true; return this._inflight; }
    this._inflight = this._loadOnce();
    return this._inflight;
  }

  async _loadOnce() {
    this._busy = true; const seq = ++this._seq;
    this._refreshBtn.classList.add('spin');
    try {
      const data = await this._service('network_inventory', {filter: 'all'});
      if (seq !== this._seq) return;
      this._data = data; this._error = ''; this._loadedAt = Date.now();
      this._scheduleScanPoll();
    } catch (e) {
      this._error = `Не удалось получить список устройств: ${this._errText(e)}`;
    } finally {
      this._busy = false; this._refreshBtn.classList.remove('spin');
      // Don't wipe a half-typed rename: the list is redrawn when the editor closes.
      this._render(!!this._editing);
    }
    // An action finished while a refresh was already in flight: fetch once more so
    // the result (e.g. the "pinned" badge) shows up immediately.
    if (this._reloadWanted) { this._reloadWanted = false; await this._load(); }
  }

  _scheduleScanPoll() {
    clearTimeout(this._scanTimer);
    if (this._data?.scan?.running) this._scanTimer = setTimeout(() => this._load(), 10000);
  }

  _errText(e) {
    const m = String(e?.message || e || 'ошибка');
    return ({invalid_mac: 'некорректный MAC', invalid_ip: 'некорректный IP', invalid_icon: 'иконка должна быть вида mdi:имя',
      invalid_name: 'недопустимое имя', name_or_icon_required: 'укажите имя или иконку'})[m] || m;
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent('hass-notification', {detail: {message}, bubbles: true, composed: true}));
  }

  async _act(mac, fn, okText) {
    this._pending.add(mac); this._renderList();
    try {
      const res = await fn();
      this._confirm = null; this._editing = null;
      this._toast(typeof okText === 'function' ? okText(res) : okText);
      await this._load();
    } catch (e) {
      this._toast(`Ошибка: ${this._errText(e)}`);
    } finally {
      this._pending.delete(mac); this._renderList();
    }
  }

  _pin(d) {
    const dry = !!this._config.dry_run;
    // Only a real device name goes to the router's lease table, never a UI placeholder.
    const leaseName = (d.hostname || (d.names || []).find(Boolean) || '').slice(0, 64);
    this._act(d.mac, () => this._service('network_pin', {mac: d.mac, ip: d.ip, name: leaseName, dry_run: dry}),
      dry ? `Тест (dry-run): ${d.ip} был бы закреплён за ${d.mac}` : `${d.ip} закреплён за ${this._name(d)}`);
  }
  _unpin(d) {
    const dry = !!this._config.dry_run;
    this._act(d.mac, () => this._service('network_unpin', {mac: d.mac, dry_run: dry}),
      dry ? `Тест (dry-run): резервирование ${d.mac} было бы снято` : `Резервирование для ${this._name(d)} снято`);
  }
  _alias(d, name, icon) {
    this._act(d.mac, () => this._service('network_alias', {mac: d.mac, name, icon}), 'Сохранено');
  }
  async _scan(d) {
    if (d) {
      this._act(d.mac, () => this._service('network_scan', {ip: d.ip}),
        r => r.busy ? 'Уже идёт сканирование, попробуйте позже' : r.done ? `${d.ip}: веб-интерфейсы проверены` : `${d.ip}: сканирование продолжается в фоне`);
      return;
    }
    this._scanBtn.disabled = true;
    try {
      const r = await this._service('network_scan', {});
      this._toast(r.busy ? 'Сканирование уже идёт' : 'Сканирование запущено — результаты появятся через пару минут');
      await this._load();
    } catch (e) {
      this._toast(`Ошибка сканирования: ${this._errText(e)}`);
    } finally {
      this._scanBtn.disabled = false; this._render();
    }
  }

  /* ---------- helpers ---------- */
  _name(d) {
    return d.hostname || (d.names || []).find(Boolean) || d.vendor || (d.random_mac ? 'Устройство со случайным MAC' : 'Неизвестное устройство');
  }
  _iconFor(d) {
    if (ND_MDI.test(d.icon || '') && d.icon !== 'mdi:lan-connect' && d.icon !== 'mdi:help-network') return d.icon;
    const hay = [d.hostname, ...(d.names || []), d.vendor, ...(d.services || []).map(s => s.title)].filter(Boolean).join(' ');
    for (const [re, icon] of ND_ICON_RULES) if (re.test(hay)) return icon;
    if (ND_MDI.test(d.icon || '')) return d.icon;
    return d.random_mac ? 'mdi:incognito' : 'mdi:lan-connect';
  }
  _ts(v) { const t = v ? Date.parse(v) : NaN; return Number.isFinite(t) ? t : 0; }
  _ago(v) {
    const t = this._ts(v); if (!t) return '—';
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return 'только что';
    if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
    if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
    if (s < 86400 * 60) return `${Math.floor(s / 86400)} дн назад`;
    return new Date(t).toLocaleDateString('ru-RU');
  }
  _ipKey(ip) { return String(ip || '').split('.').reduce((a, o) => a * 256 + (parseInt(o, 10) || 0), 0); }
  _isNew(d) { return Date.now() - this._ts(d.first_seen) <= this._config.new_hours * 3600e3; }
  _matches(d, f) {
    switch (f) {
      case 'recent': return d.online || Date.now() - this._ts(d.last_seen) <= this._config.recent_hours * 3600e3;
      case 'active': return !!d.online;
      case 'pinned': return !!d.reserved_ip;
      case 'new': return this._isNew(d);
      case 'unknown': return !d.vendor;
      default: return true;
    }
  }
  _serviceUrl(s, d) {
    try {
      const u = new URL(s.url || `${s.scheme || 'http'}://${d.ip}:${s.port}/`);
      return (u.protocol === 'http:' || u.protocol === 'https:') ? u.href : null;
    } catch (e) { return null; }
  }

  /* ---------- rendering ---------- */
  _render(skipList = false) {
    if (!this._built || !this._config) return;
    this._title.textContent = this._config.title || 'Устройства в сети';
    if (this._config.dry_run) this._node('span', 'тестовый режим', this._title, 'test').title = 'Закрепление/снятие IP вызывает router-cli с --dry-run';
    const devices = this._data?.devices || [];
    const online = devices.filter(d => d.online).length;
    const parts = [];
    if (this._data) {
      parts.push(`${devices.length} устройств, ${online} онлайн`);
      const r = this._data.router || {};
      if (r.model || r.host) parts.push(`роутер ${[r.model, r.host].filter(Boolean).join(' · ')}`);
      if (this._data.generated_at) parts.push(`данные ${this._ago(this._data.generated_at)}`);
      if (this._data.scan?.running) parts.push(`идёт сканирование: ${this._data.scan.running}`);
    } else if (!this._error) parts.push('Загрузка…');
    this._summary.textContent = parts.join(' · ');
    this._scanBtn.classList.toggle('spin', !!this._data?.scan?.running);
    this._err.textContent = this._error;
    this._chips.replaceChildren();
    for (const [key, label] of ND_FILTERS) {
      const b = this._button(null, null, this._chips, 'chip', () => { this._filter = key; this._render(); });
      this._node('span', label, b);
      this._node('span', String(devices.filter(d => this._matches(d, key)).length), b, 'n');
      b.setAttribute('aria-pressed', String(this._filter === key));
    }
    this._sortSel.value = this._sort;
    if (!skipList) this._renderList();
  }

  _renderList() {
    if (!this._built) return;
    const q = this._query;
    let items = (this._data?.devices || []).filter(d => this._matches(d, this._filter));
    if (q) items = items.filter(d => [this._name(d), d.hostname, ...(d.names || []), d.ip, d.mac, d.vendor, d.reserved_ip,
      ...(d.services || []).map(s => s.title)].filter(Boolean).join(' ').toLowerCase().includes(q));
    const byName = (a, b) => this._name(a).localeCompare(this._name(b), 'ru');
    const cmp = {
      last_seen: (a, b) => (b.online - a.online) || (this._ts(b.last_seen) - this._ts(a.last_seen)) || byName(a, b),
      name: byName,
      ip: (a, b) => this._ipKey(a.ip) - this._ipKey(b.ip),
    }[this._sort];
    items.sort(cmp);
    const frag = document.createDocumentFragment();
    for (const d of items) frag.append(this._row(d));
    if (!items.length && this._data) this._node('div', q ? 'Ничего не найдено' : 'Нет устройств для этого фильтра', frag, 'empty');
    this._list.replaceChildren(frag);
    const total = this._data?.devices?.length || 0;
    this._foot.textContent = this._data ? `Показано ${items.length} из ${total}. Автообновление каждые ${Math.max(15, Number(this._config.refresh_interval) || 60)} с.` : '';
  }

  _row(d) {
    const admin = !!this._hass?.user?.is_admin;
    const busy = this._pending.has(d.mac);
    const row = this._node('div', null, null, `row${d.online ? '' : ' offline'}`);
    const av = this._node('div', null, row, 'avatar');
    this._icon(this._iconFor(d), av);
    const dot = this._node('span', null, av, `dot${d.online ? ' on' : ''}`);
    dot.title = d.online ? 'онлайн' : 'офлайн';
    const main = this._node('div', null, row, 'main');
    const nm = this._node('div', null, main, 'name');
    this._node('span', this._name(d), nm);
    if (this._isNew(d)) { nm.append(' '); this._node('span', 'новое', nm, 'badge new'); }
    if (d.random_mac) { nm.append(' '); const b = this._node('span', null, nm, 'badge'); this._icon('mdi:incognito', b); this._node('span', 'случайный MAC', b); b.title = 'Приватный (рандомизированный) MAC-адрес — IP может меняться'; }

    const l1 = this._node('div', null, main, 'line');
    this._node('span', d.ip || '—', l1, 'mono ip');
    if (d.reserved_ip && d.reserved_ip === d.ip) {
      const b = this._node('span', null, l1, 'badge pin'); this._icon('mdi:pin', b); this._node('span', 'закреплён', b);
    } else if (d.reserved_ip) {
      const b = this._node('span', null, l1, 'badge warn'); this._icon('mdi:alert', b);
      this._node('span', `IP изменился: закреплён ${d.reserved_ip}`, b);
    }
    const prev = (d.ip_history || []).filter(ip => ip && ip !== d.ip);
    if (prev.length) this._node('span', `ранее: ${[...new Set(prev)].slice(-3).join(', ')}`, l1).title = 'История IP';

    const l2 = this._node('div', null, main, 'line');
    this._node('span', d.mac, l2, 'mono');
    if (d.vendor) this._node('span', d.vendor, l2);
    if (d.interface) {
      const s = this._node('span', null, l2);
      const wifi = /wi-?fi|wlan|wireless|5g|2\.4/i.test(d.interface);
      this._icon(wifi ? 'mdi:wifi' : 'mdi:ethernet', s, 'if');
      s.append(` ${wifi ? 'Wi‑Fi' : d.interface === 'lan' ? 'LAN' : d.interface}`);
    }
    const l3 = this._node('div', null, main, 'line');
    this._node('span', d.online ? 'онлайн' : `был ${this._ago(d.last_seen)}`, l3).title = d.last_seen ? new Date(this._ts(d.last_seen)).toLocaleString('ru-RU') : '';
    this._node('span', `впервые ${this._ago(d.first_seen)}`, l3).title = d.first_seen ? new Date(this._ts(d.first_seen)).toLocaleString('ru-RU') : '';

    const svcs = (d.services || []).map(s => [s, this._serviceUrl(s, d)]).filter(([, u]) => u);
    if (svcs.length) {
      const box = this._node('div', null, main, 'svcs');
      for (const [s, url] of svcs.sort((a, b) => (a[0].port || 0) - (b[0].port || 0))) {
        const a = this._node('a', null, box, 'svc');
        a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.title = [s.title, s.server, url, s.checked_at ? `проверено ${this._ago(s.checked_at)}` : ''].filter(Boolean).join('\n');
        const fav = typeof s.favicon_data_url === 'string' && /^data:image\/(png|x-icon|vnd\.microsoft\.icon|gif|jpeg|svg\+xml|webp);/i.test(s.favicon_data_url);
        if (fav) { const img = this._node('img', null, a); img.src = s.favicon_data_url; img.alt = ''; img.loading = 'lazy'; }
        else this._icon(s.scheme === 'https' ? 'mdi:web-check' : 'mdi:web', a);
        this._node('span', (s.title || '').trim() || s.server || (s.scheme || 'http').toUpperCase(), a, 't');
        this._node('span', `:${s.port}`, a, 'p');
      }
    }

    const acts = this._node('div', null, row, 'acts');
    if (admin) {
      const pinned = d.reserved_ip && d.reserved_ip === d.ip;
      if (!pinned && d.ip) {
        const b = this._button(d.reserved_ip ? 'Перезакрепить' : 'Закрепить IP', 'mdi:pin-outline', acts, '',
          () => { this._confirm = {mac: d.mac, action: 'pin'}; this._editing = null; this._renderList(); });
        b.title = `Зарезервировать ${d.ip} за ${d.mac} в DHCP роутера`; b.disabled = busy;
      }
      if (d.reserved_ip) {
        const b = this._button('', 'mdi:pin-off-outline', acts, 'icon',
          () => { this._confirm = {mac: d.mac, action: 'unpin'}; this._editing = null; this._renderList(); });
        b.title = 'Снять резервирование'; b.setAttribute('aria-label', 'Снять резервирование'); b.disabled = busy;
      }
      const sc = this._button('', 'mdi:web-refresh', acts, `icon${busy ? ' spin' : ''}`, () => this._scan(d));
      sc.title = 'Проверить веб-интерфейсы'; sc.setAttribute('aria-label', 'Проверить веб-интерфейсы'); sc.disabled = busy || !d.ip;
      const ed = this._button('', 'mdi:pencil', acts, 'icon',
        () => { this._editing = this._editing === d.mac ? null : d.mac; this._confirm = null; this._renderList(); });
      ed.title = 'Имя и иконка'; ed.setAttribute('aria-label', 'Имя и иконка'); ed.disabled = busy;
    }

    if (admin && this._confirm?.mac === d.mac) this._confirmPanel(d, row, busy);
    if (admin && this._editing === d.mac) this._editPanel(d, row, busy);
    return row;
  }

  _confirmPanel(d, row, busy) {
    const p = this._node('div', null, row, 'panel');
    const pin = this._confirm.action === 'pin';
    const dry = this._config.dry_run ? ' (тест, --dry-run)' : '';
    this._node('span', pin
      ? `Закрепить ${d.ip} за ${d.mac} (${this._name(d)})${d.reserved_ip ? `, заменив ${d.reserved_ip}` : ''}?${dry}`
      : `Снять резервирование ${d.reserved_ip} для ${d.mac}?${dry}`, p);
    const yes = this._button(pin ? 'Закрепить' : 'Снять', pin ? 'mdi:pin' : 'mdi:pin-off', p, pin ? 'primary' : 'danger',
      () => pin ? this._pin(d) : this._unpin(d));
    yes.disabled = busy;
    this._button('Отмена', null, p, '', () => { this._confirm = null; this._renderList(); });
    if (!busy) requestAnimationFrame(() => yes.focus());
  }

  _editPanel(d, row, busy) {
    const p = this._node('div', null, row, 'panel');
    const name = this._node('input', null, p);
    name.value = this._name(d); name.maxLength = 64; name.placeholder = 'Имя'; name.setAttribute('aria-label', 'Имя устройства');
    const preview = this._icon(this._iconFor(d), p, 'preview');
    const icon = this._node('input', null, p);
    // Pre-fill only a real icon from router-cli; the client-side guess is just the placeholder,
    // so a plain rename doesn't freeze the heuristic icon as a permanent override.
    const origIcon = ND_MDI.test(d.icon || '') && d.icon === this._iconFor(d) ? d.icon : '';
    const origName = this._name(d);
    icon.value = origIcon; icon.placeholder = this._iconFor(d); icon.setAttribute('aria-label', 'Иконка (mdi:…)');
    icon.addEventListener('input', () => { const v = icon.value.trim().toLowerCase(); preview.setAttribute('icon', ND_MDI.test(v) ? v : this._iconFor(d)); });
    const save = () => {
      const v = icon.value.trim().toLowerCase();
      if (v && !ND_MDI.test(v)) { this._toast('Иконка должна быть вида mdi:имя'); return; }
      const n = name.value.trim();
      const newName = n !== origName ? n : '';
      const newIcon = v !== origIcon ? v : '';
      if (!newName && !newIcon) { this._editing = null; this._renderList(); return; }
      this._alias(d, newName, newIcon);
    };
    for (const inp of [name, icon]) inp.addEventListener('keydown', e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { this._editing = null; this._renderList(); } });
    this._button('Сохранить', 'mdi:content-save', p, 'primary', save).disabled = busy;
    this._button('Отмена', null, p, '', () => { this._editing = null; this._renderList(); });
    if (!busy) requestAnimationFrame(() => name.focus());
  }

  static getStubConfig() { return {default_filter: 'recent'}; }
}

if (!customElements.get('network-devices-card')) customElements.define('network-devices-card', NetworkDevicesCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === 'network-devices-card')) {
  window.customCards.push({type: 'network-devices-card', name: 'Network devices', description: 'Router inventory with web UIs and DHCP pinning (router-cli)'});
}
