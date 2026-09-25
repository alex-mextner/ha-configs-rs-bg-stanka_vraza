// Wakeword Studio card: microphone, background-noise recording, wake-phrase
// choice, guided phrase recording and review of the recorded clips.
// Backend: custom_components/wakeword_studio (authenticated /api/wakeword_studio/*).

const TABS = [
  { id: "mic", label: "Микрофон", icon: "M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z" },
  { id: "noise", label: "Шум", icon: "M3 12h2v-2H3v2Zm4 4h2V8H7v8Zm4 4h2V4h-2v16Zm4-4h2V8h-2v8Zm4-6v4h2v-4h-2Z" },
  { id: "phrase", label: "Фраза", icon: "M4 4h16v12H5.17L4 17.17V4Zm2 4v2h12V8H6Zm0 3v2h8v-2H6Z" },
  { id: "record", label: "Запись", icon: "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10Zm0-5a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Z" },
  { id: "voices", label: "Голоса", icon: "M9 5a4 4 0 1 1 0 8 4 4 0 0 1 0-8Zm0 10c4.42 0 8 1.79 8 4v2H1v-2c0-2.21 3.58-4 8-4Zm7.76-9.64c2.02 2.2 2.02 5.25 0 7.27l-1.68-1.69c.84-1.18.84-2.71 0-3.89l1.68-1.69ZM20.07 2c3.93 4.05 3.9 10.11 0 14l-1.63-1.63c2.77-3.18 2.77-7.72 0-10.74L20.07 2Z" },
  { id: "review", label: "Разметка", icon: "M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17Z" },
  { id: "train", label: "Обучение", icon: "M3.5 18.49l6-6.01 4 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z" },
];

const STYLES = [
  ["normal", "Обычно"], ["whisper", "Шёпотом"], ["loud", "Громко"], ["tired", "Устало"],
  ["fast", "Быстро"], ["moving", "На ходу"],
];
const LOCATIONS = [
  ["near_1m", "Рядом, ~1 м"], ["sofa_3m", "С дивана, ~3 м"], ["kitchen", "Кухня"],
  ["hallway", "Коридор"], ["other_room", "Другая комната"], ["tv_on", "При ТВ/музыке"],
];
const COUNTS = [10, 20, 30, 50];
const ZONE_KINDS = [["people", "Люди"], ["tv", "ТВ"], ["speaker", "Колонка"], ["other", "Другое"]];
const ZONE_COLORS = { people: "var(--success-color, #43a047)", tv: "var(--error-color, #e53935)", speaker: "var(--info-color, #039be5)", other: "var(--secondary-text-color)" };
const angDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);
const circMean = (angles) => {
  if (!angles.length) return null;
  const s = angles.reduce((acc, d) => acc + Math.sin((d * Math.PI) / 180), 0);
  const c = angles.reduce((acc, d) => acc + Math.cos((d * Math.PI) / 180), 0);
  return Math.round(((Math.atan2(s, c) * 180) / Math.PI + 360) % 360);
};
const zoneOf = (zones, deg) => (deg == null ? null : (zones || []).find((z) => angDiff(deg, z.center) <= z.width / 2) || null);
const VERDICTS = {
  good: ["Хорошо", "var(--success-color, #43a047)"],
  risky: ["Сомнительно", "var(--warning-color, #fb8c00)"],
  bad: ["Плохо", "var(--error-color, #e53935)"],
  unknown: ["Нет данных", "var(--secondary-text-color)"],
};
const REVIEW_FILTERS = [
  ["active", "Без отклонённых"], ["pending", "Ожидают"], ["confirmed", "Подтверждённые"],
  ["rejected", "Отклонённые"], ["all", "Все"],
];
const PAGE = 40;

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtHours = (h) => (h == null ? "—" : h < 1 ? `${Math.round(h * 60)} мин` : `${h.toFixed(1)} ч`);
const fmtEta = (h) => (h == null ? "—" : h > 36 ? `~${(h / 24).toFixed(1)} сут` : `~${Math.round(h)} ч`);
const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
};
const store = {
  get(k, d) { try { const v = localStorage.getItem(`wakeword-studio:${k}`); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`wakeword-studio:${k}`, JSON.stringify(v)); } catch { /* private mode */ } },
};

class WakewordStudioCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._tab = store.get("tab", "mic");
    this._state = null;
    this._clips = [];
    this._clipsLoadedAt = 0;
    this._filter = store.get("filter", "active");
    this._shown = PAGE;
    this._playing = null;
    this._playlist = false;
    this._setup = store.get("setup", { speaker: "", style: "normal", location: "near_1m", expected: 20 });
    this._lastCaptured = null;
    this._busy = new Set();
    this._error = "";
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._boot();
  }

  getCardSize() { return 12; }

  connectedCallback() {
    this._alive = true;
    if (this._hass) this._schedule(0);
  }

  disconnectedCallback() {
    this._alive = false;
    clearTimeout(this._timer);
    this._stopAudio();
  }

  _boot() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${CSS}</style>
      <ha-card>
        <div class="head">
          <div class="title">Голос · Студия</div>
          <div class="chips" id="chips"></div>
        </div>
        <nav class="tabs">${TABS.map((t) => `
          <button class="tab" data-tab="${t.id}"><svg viewBox="0 0 24 24"><path d="${t.icon}"/></svg><span>${t.label}</span></button>`).join("")}
        </nav>
        <div class="err" id="err" hidden></div>
        <section data-pane="mic"></section>
        <section data-pane="noise"></section>
        <section data-pane="phrase"></section>
        <section data-pane="record"></section>
        <section data-pane="voices"></section>
        <section data-pane="review"></section>
        <section data-pane="train"></section>
      </ha-card>`;
    this.shadowRoot.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => this._selectTab(b.dataset.tab)));
    this._buildPanes();
    this._selectTab(this._tab);
    this._schedule(0);
  }

  // ------------------------------------------------------------------ data
  async _api(method, path, body) {
    return this._hass.callApi(method, `wakeword_studio/${path}`, body);
  }

  _schedule(delay) {
    clearTimeout(this._timer);
    if (!this._alive && this.isConnected === false) return;
    this._timer = setTimeout(() => this._poll(), delay);
  }

  async _poll() {
    if (!this._hass) return;
    try {
      this._state = await this._api("GET", "state");
      this._setError("");
    } catch (e) {
      this._setError(`Нет связи с wakeword_studio: ${e?.body?.message || e?.message || e}`);
    }
    if (this._state) this._update();
    if (this._tab === "review" && Date.now() - this._clipsLoadedAt > 15000) this._loadClips();
    const live = this._tab === "mic" || this._tab === "record" || this._tab === "voices";
    this._schedule(document.hidden ? 5000 : live ? 400 : 2500);
  }

  async _loadClips(force = false) {
    if (!force && this._clipsLoading) return;
    this._clipsLoading = true;
    try {
      const res = await this._api("GET", "review");
      this._clips = res.clips || [];
      this._clipsLoadedAt = Date.now();
      this._renderReviewList();
    } catch (e) {
      this._setError(`Не удалось загрузить записи: ${e?.message || e}`);
    } finally {
      this._clipsLoading = false;
    }
  }

  _setError(msg) {
    const el = this.shadowRoot?.getElementById("err");
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg;
  }

  async _act(key, fn) {
    if (this._busy.has(key)) return;
    this._busy.add(key);
    this._update();
    try {
      await fn();
      this._setError("");
    } catch (e) {
      this._setError(e?.body?.message || e?.message || String(e));
    } finally {
      this._busy.delete(key);
      this._schedule(0);
    }
  }

  _selectTab(id) {
    this._tab = id;
    store.set("tab", id);
    this.shadowRoot.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === id));
    this.shadowRoot.querySelectorAll("section[data-pane]").forEach((s) => (s.hidden = s.dataset.pane !== id));
    if (id === "review") this._loadClips(true);
    this._schedule(0);
  }

  // ------------------------------------------------------------------ static panes
  _buildPanes() {
    const $ = (id) => this.shadowRoot.querySelector(`section[data-pane="${id}"]`);
    $("mic").innerHTML = `
      <div class="grid2">
        <div class="compass-wrap"><svg id="compass" viewBox="-120 -120 240 240"></svg></div>
        <div class="stack">
          <div class="kv"><span>Уровень</span><b id="lvl-val">—</b></div>
          <div class="meter"><div id="lvl-bar"></div><div id="lvl-peak" class="peak"></div></div>
          <div class="kv"><span>Речь (детектор чипа)</span><b id="vad">—</b></div>
          <div class="kv"><span>Направление</span><b id="dir">—</b></div>
          <div class="kv"><span>Источник направления</span><b id="dir-src">—</b></div>
          <div class="kv"><span>AGC чипа</span><b id="agc">—</b></div>
          <div class="kv"><span>Захват звука</span><b id="cap">—</b></div>
          <div class="kv"><span>Зона</span><b id="zone-now">—</b></div>
          <p class="hint" id="sector-hint"></p>
        </div>
      </div>
      <h3>Зоны комнаты</h3>
      <div id="zones"></div>
      <div class="row">
        <input id="zone-name" placeholder="Название: Диван, ТВ, Кухня…" maxlength="30">
        <div class="seg" id="zone-kind"></div>
        <button class="btn" id="zone-add">Запомнить текущее направление</button>
      </div>
      <p class="hint">Встаньте или включите источник звука там, где зона, и нажмите кнопку: сохранится направление последних секунд речи (±20°). Зоны типа «ТВ/колонка» потом используются, чтобы не доверять срабатываниям с их стороны.</p>
      <p class="hint">Направление и детектор речи считает сам DSP-чип XMOS XVF-3000 в ReSpeaker по разнице времени прихода звука на 4 микрофона. Оранжевое кольцо — откуда за последние 24 часа звучала речь.</p>`;

    $("noise").innerHTML = `
      <div class="row between"><div class="big" id="noise-state">—</div><div id="noise-actions"></div></div>
      <div class="progress"><div id="noise-bar"></div></div>
      <div class="row between small"><span id="noise-hours">—</span><span id="noise-eta"></span></div>
      <div class="grid-kv" id="noise-kv"></div>
      <div class="note">
        <b>Что это.</b> Микрофон неделю пишет обычную жизнь дома: разговоры, ТВ, музыку, кухню. Модель учится на этом <i>не</i> реагировать.
        Пока идёт запись, не произносите выбранную фразу рядом с колонкой. Обсуждать варианты можно: такие места найдутся по расшифровке и будут вырезаны.
        Во время записи фразы (вкладка «Запись») шум автоматически не пишется.
      </div>`;

    $("phrase").innerHTML = `
      <div class="selected" id="phrase-selected"></div>
      <div class="row"><input id="phrase-input" placeholder="Вариант фразы, например: Эй, Джарвис" maxlength="60">
        <button class="btn primary" id="phrase-check">Проверить</button></div>
      <div id="phrase-result"></div>
      <h3>Проверенные варианты</h3>
      <div id="phrase-table"></div>
      <div class="note" id="phrase-corpus"></div>
      <details class="note"><summary><b>Как выбрать хорошую фразу</b></summary>
        <ul>
          <li>3–4 слога и не меньше 6–7 звуков: «Милош» — 2 слога, поэтому путается с «милая», «миль от».</li>
          <li>Ударный ясный гласный и хотя бы один редкий звук: дж, ж, ф, ц, щ.</li>
          <li>Не имя человека в доме, не бренд и не слово из ТВ («Алиса» звучит у вас ~0.6 раз в час).</li>
          <li>Проверка ищет похожие по звучанию слова в расшифровке ваших домашних записей: чем меньше совпадений в час, тем меньше ложных срабатываний.</li>
        </ul></details>`;

    $("voices").innerHTML = `
      <div id="voices-live"></div>
      <div id="voices-users"></div>
      <h3>Гость</h3>
      <div class="row"><input id="guest-name" placeholder="Имя гостя" maxlength="40">
        <div class="seg" id="guest-days"></div>
        <button class="btn primary" id="guest-start">Записать гостя</button></div>
      <div id="voices-guests"></div>
      <div class="note">
        <b>Зачем.</b> Колонка будет узнавать, кто говорит, и включать вашу музыку, ваши напоминания и ваши настройки (как «Алиса узнаёт по голосу»).
        Нужно 5 раз сказать фразу и прочитать 8 коротких команд — с того места, откуда вы обычно говорите.
        Записи хранятся только на этом сервере и удаляются кнопкой «Удалить голос». Голос никогда не открывает замки и не подтверждает платежи.
        Гостевой голос удаляется сам через выбранное число дней.
      </div>`;
    this._guestDays = 3;
    this._fillSeg("guest-days", [[1, "1 день"], [3, "3 дня"], [7, "7 дней"]], () => this._guestDays, (v) => (this._guestDays = Number(v)));
    this.shadowRoot.getElementById("guest-start").addEventListener("click", () => {
      const name = this.shadowRoot.getElementById("guest-name").value.trim();
      if (!name) { this._setError("Введите имя гостя."); return; }
      this._voiceStart({ guest: name, days: this._guestDays }, "enroll_phrase");
    });

    $("train").innerHTML = `
      <div id="train-list"></div>
      <div class="note">
        <b>Как это устроено.</b> Модель учится на синтетических произнесениях фразы разными голосами и акцентами, смешанных с записанным шумом вашего дома,
        а принимается только по отложенным данным: день домашнего шума, который она не видела (ложные срабатывания в час), и голоса, которых не было в обучении (полнота).
        Когда обучение закончится или упадёт, придёт уведомление в Home Assistant.
      </div>`;

    $("record").innerHTML = `
      <div id="rec-need-phrase" class="note warn" hidden>Сначала выберите фразу во вкладке «Фраза».</div>
      <div id="rec-setup">
        <label class="lbl">Кто говорит</label>
        <div class="row"><input id="rec-speaker" list="rec-speakers" placeholder="Имя, например: Андрей" maxlength="40"><datalist id="rec-speakers"></datalist></div>
        <label class="lbl">Как</label><div class="seg" id="rec-style"></div>
        <label class="lbl">Где</label><div class="seg" id="rec-location"></div>
        <label class="lbl">Сколько раз</label><div class="seg" id="rec-count"></div>
        <button class="btn primary wide" id="rec-start">Начать запись</button>
      </div>
      <div id="rec-live" hidden>
        <div class="say">Скажите: «<span id="rec-phrase"></span>»</div>
        <div class="counter"><span id="rec-count-now">0</span><small>/ <span id="rec-count-target">0</span></small></div>
        <div class="progress"><div id="rec-bar"></div></div>
        <div class="meter"><div id="rec-lvl"></div></div>
        <p class="hint">Произносите фразу с паузой 3–5 секунд. Каждая попытка записывается автоматически, щелчок значит, что клип сохранён.</p>
        <button class="btn wide" id="rec-finish">Завершить</button>
      </div>
      <h3>Уже записано</h3>
      <div id="rec-summary" class="small"></div>
      <details class="note"><summary><b>Минимальный набор на человека</b></summary>
        <ul><li>30 раз рядом, обычным голосом</li><li>20 раз с дивана/из коридора</li>
        <li>по 10 шёпотом, громко, устало</li><li>20 раз при включённом ТВ или музыке</li>
        <li>каждый житель дома и 1–2 гостя</li></ul></details>`;

    $("review").innerHTML = `
      <div class="row between">
        <div class="seg" id="rv-filter"></div>
        <button class="btn" id="rv-play">▶ Слушать подряд</button>
      </div>
      <div class="small" id="rv-count"></div>
      <div class="list" id="rv-list"></div>
      <div id="rv-more" class="sentinel"></div>`;

    this._zoneKind = "people";
    this._fillSeg("zone-kind", ZONE_KINDS, () => this._zoneKind, (v) => { this._zoneKind = v; });
    this._fillSeg("rec-style", STYLES, () => this._setup.style, (v) => { this._setup.style = v; store.set("setup", this._setup); });
    this._fillSeg("rec-location", LOCATIONS, () => this._setup.location, (v) => { this._setup.location = v; store.set("setup", this._setup); });
    this._fillSeg("rec-count", COUNTS.map((c) => [c, String(c)]), () => this._setup.expected, (v) => { this._setup.expected = Number(v); store.set("setup", this._setup); });
    this._fillSeg("rv-filter", REVIEW_FILTERS, () => this._filter, (v) => { this._filter = v; store.set("filter", v); this._shown = PAGE; this._renderReviewList(); });

    const r = this.shadowRoot;
    const speaker = r.getElementById("rec-speaker");
    speaker.value = this._setup.speaker || "";
    speaker.addEventListener("input", () => { this._setup.speaker = speaker.value.trim(); store.set("setup", this._setup); });
    r.getElementById("rec-start").addEventListener("click", () => this._startPositive());
    r.getElementById("rec-finish").addEventListener("click", () => this._act("positive", () => this._api("POST", "positive", { action: "finish" })));
    r.getElementById("phrase-check").addEventListener("click", () => this._checkPhrase());
    r.getElementById("phrase-input").addEventListener("keydown", (e) => { if (e.key === "Enter") this._checkPhrase(); });
    r.getElementById("rv-play").addEventListener("click", () => this._togglePlaylist());
    r.getElementById("zone-add").addEventListener("click", () => this._addZone());
    this._observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && this._shown < this._filtered().length) {
        this._shown += PAGE;
        this._renderReviewList();
      }
    });
    this._observer.observe(r.getElementById("rv-more"));
    this._drawCompassBase();
  }

  _fillSeg(id, items, get, set) {
    const el = this.shadowRoot.getElementById(id);
    el.innerHTML = items.map(([v, l]) => `<button data-v="${esc(v)}">${esc(l)}</button>`).join("");
    const paint = () => el.querySelectorAll("button").forEach((b) => b.classList.toggle("on", String(get()) === b.dataset.v));
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      set(b.dataset.v);
      paint();
    });
    paint();
  }

  // ------------------------------------------------------------------ updates
  _update() {
    const s = this._state;
    if (!s) return;
    this._updateChips(s);
    if (this._tab === "mic") this._updateMic(s);
    if (this._tab === "noise") this._updateNoise(s);
    if (this._tab === "phrase") this._updatePhrase(s);
    if (this._tab === "record") this._updateRecord(s);
    if (this._tab === "review") this._updateReviewHeader(s);
    if (this._tab === "train") this._updateTrain(s);
    if (this._tab === "voices") this._updateVoices(s);
  }

  _updateChips(s) {
    const a = s.array || {};
    const n = s.noise || {};
    const sel = s.phrase?.selected;
    const chip = (ok, text) => `<span class="chip ${ok === true ? "ok" : ok === false ? "bad" : ""}">${esc(text)}</span>`;
    this.shadowRoot.getElementById("chips").innerHTML = [
      chip(a.capture_ok, a.capture_ok ? "Микрофон на связи" : "Микрофон: нет данных"),
      chip(n.state === "recording" ? true : null, n.state === "recording" ? `Шум: ${fmtHours(n.raw_live?.hours_since_start)}` : "Шум не пишется"),
      chip(sel ? true : null, sel ? `Фраза: «${sel.phrase}»` : "Фраза не выбрана"),
      s.positive?.active ? chip(true, "Идёт запись фразы") : "",
      ...(s.training?.pipelines || []).filter((p) => p.state === "running" || p.state === "failed").map((p) =>
        chip(p.state === "running" ? true : false, p.state === "running" ? `Обучение: ${Math.round((p.progress || 0) * 100)}%` : "Обучение: ошибка")),
    ].join("");
  }

  _drawCompassBase() {
    const svg = this.shadowRoot.getElementById("compass");
    let ticks = "";
    for (let d = 0; d < 360; d += 30) {
      const a = ((d - 90) * Math.PI) / 180;
      const [x1, y1, x2, y2] = [Math.cos(a) * 92, Math.sin(a) * 92, Math.cos(a) * 100, Math.sin(a) * 100];
      const [lx, ly] = [Math.cos(a) * 111, Math.sin(a) * 111 + 3];
      ticks += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="tick"/><text x="${lx}" y="${ly}" class="lbl-deg">${d}</text>`;
    }
    svg.innerHTML = `<g id="zones-g"></g><g id="heat"></g><circle r="86" class="ring"/>${ticks}<g id="trail"></g>
      <line id="needle" x1="0" y1="0" x2="0" y2="-80" class="needle"/><circle r="30" id="hub" class="hub"/>
      <text id="hub-text" y="5" class="hub-text">—</text>`;
  }

  _updateMic(s) {
    const a = s.array || {};
    const r = this.shadowRoot;
    const lvl = a.level_dbfs;
    r.getElementById("lvl-val").textContent = lvl == null ? "—" : `${lvl.toFixed(1)} dBFS`;
    const pct = lvl == null ? 0 : Math.max(0, Math.min(100, ((lvl + 80) / 80) * 100));
    r.getElementById("lvl-bar").style.width = `${pct}%`;
    this._peak = Math.max((this._peak || 0) * 0.97, pct);
    r.getElementById("lvl-peak").style.left = `${this._peak}%`;
    const speech = a.speech_detected === 1;
    r.getElementById("vad").textContent = a.speech_detected == null ? "нет данных" : speech ? "говорят" : a.voice_activity ? "звук" : "тишина";
    r.getElementById("dir").textContent = a.direction_degrees == null ? "—" : `${a.direction_degrees}°`;
    r.getElementById("dir-src").textContent = a.direction_source === "xvf3000_doa" ? "чип XVF-3000" : "недоступно";
    r.getElementById("agc").textContent = a.agc_on == null ? "—" : a.agc_on === 1 ? `вкл, усиление ×${a.agc_gain ?? "?"}` : a.agc_on === 0 ? "выкл" : "не читается";
    r.getElementById("cap").textContent = a.capture_ok ? "идёт" : `нет данных ${a.capture_age ?? ""} с`;

    const needle = r.getElementById("needle");
    if (a.direction_degrees == null) needle.setAttribute("visibility", "hidden");
    else {
      needle.setAttribute("visibility", "visible");
      needle.setAttribute("transform", `rotate(${a.direction_degrees})`);
      needle.classList.toggle("speech", speech);
    }
    r.getElementById("hub").classList.toggle("speech", speech);
    r.getElementById("hub-text").textContent = speech ? "речь" : a.direction_degrees == null ? "—" : `${a.direction_degrees}°`;
    r.getElementById("trail").innerHTML = (a.speech_trail_degrees || []).map((d, i, arr) => {
      const ang = ((d - 90) * Math.PI) / 180;
      return `<circle cx="${Math.cos(ang) * 70}" cy="${Math.sin(ang) * 70}" r="3" class="dot" opacity="${0.2 + (0.8 * (i + 1)) / arr.length}"/>`;
    }).join("");

    const hist = s.doa_hist_24h?.counts || [];
    const total = hist.reduce((x, y) => x + y, 0);
    const max = Math.max(1, ...hist);
    const step = s.doa_hist_24h?.bin_degrees || 10;
    r.getElementById("heat").innerHTML = hist.map((c, i) => {
      if (!c) return "";
      const a0 = ((i * step - 90) * Math.PI) / 180;
      const a1 = (((i + 1) * step - 90) * Math.PI) / 180;
      const [ri, ro] = [86, 100];
      const p = `M${Math.cos(a0) * ri},${Math.sin(a0) * ri} L${Math.cos(a0) * ro},${Math.sin(a0) * ro} A${ro},${ro} 0 0 1 ${Math.cos(a1) * ro},${Math.sin(a1) * ro} L${Math.cos(a1) * ri},${Math.sin(a1) * ri} A${ri},${ri} 0 0 0 ${Math.cos(a0) * ri},${Math.sin(a0) * ri}Z`;
      return `<path d="${p}" class="heat" opacity="${(0.15 + (0.85 * c) / max).toFixed(2)}"/>`;
    }).join("");
    const zones = s.room?.zones || [];
    const nowZone = zoneOf(zones, a.direction_degrees);
    r.getElementById("zone-now").textContent = a.direction_degrees == null ? "—" : nowZone ? nowZone.name : "вне зон";
    let hint = "За последние 24 ч речь чипом ещё не зафиксирована.";
    if (total > 0) {
      const lines = zones.map((z) => {
        const n = hist.reduce((acc, c, i) => acc + (angDiff(i * step + step / 2, z.center) <= z.width / 2 ? c : 0), 0);
        return `${z.name} ${Math.round((n / total) * 100)}%`;
      });
      const top = hist.indexOf(Math.max(...hist));
      const topZone = zoneOf(zones, top * step + step / 2);
      hint = `Речь за 24 ч: ${lines.length ? lines.join(", ") + ". " : ""}Пик на ${top * step}–${(top + 1) * step}°${topZone ? ` (${topZone.name})` : ""}.`;
    }
    r.getElementById("sector-hint").textContent = hint;

    const zonesKey = JSON.stringify(zones);
    if (this._zonesKey !== zonesKey) {
      this._zonesKey = zonesKey;
      r.getElementById("zones-g").innerHTML = zones.map((z) => {
        const a0 = ((z.center - z.width / 2 - 90) * Math.PI) / 180;
        const a1 = ((z.center + z.width / 2 - 90) * Math.PI) / 180;
        const large = z.width > 180 ? 1 : 0;
        const [ri, ro] = [30, 86];
        const d = `M${Math.cos(a0) * ri},${Math.sin(a0) * ri} L${Math.cos(a0) * ro},${Math.sin(a0) * ro} A${ro},${ro} 0 ${large} 1 ${Math.cos(a1) * ro},${Math.sin(a1) * ro} L${Math.cos(a1) * ri},${Math.sin(a1) * ri} A${ri},${ri} 0 ${large} 0 ${Math.cos(a0) * ri},${Math.sin(a0) * ri}Z`;
        const am = ((z.center - 90) * Math.PI) / 180;
        return `<path d="${d}" fill="${ZONE_COLORS[z.kind] || ZONE_COLORS.other}" opacity="0.14"/>
          <text x="${Math.cos(am) * 58}" y="${Math.sin(am) * 58 + 4}" class="zone-lbl" fill="${ZONE_COLORS[z.kind] || ZONE_COLORS.other}">${esc(z.name)}</text>`;
      }).join("");
      const list = zones.length ? zones.map((z, i) => `<div class="zone-row"><span class="zone-dot" style="background:${ZONE_COLORS[z.kind] || ZONE_COLORS.other}"></span>
          <b>${esc(z.name)}</b><span class="small">${(ZONE_KINDS.find(([k]) => k === z.kind) || [0, ""])[1]} · ${z.center}° ±${Math.round(z.width / 2)}°</span>
          <button class="icon-btn" data-zone-del="${i}" title="Удалить">✕</button></div>`).join("")
        : `<div class="small">Зон пока нет.</div>`;
      const box = r.getElementById("zones");
      box.innerHTML = list;
      box.querySelectorAll("[data-zone-del]").forEach((b) => b.addEventListener("click", () => {
        const next = zones.filter((_, i) => i !== Number(b.dataset.zoneDel));
        this._act("room", () => this._api("POST", "room", { zones: next }));
      }));
    }
  }

  async _addZone() {
    const name = this.shadowRoot.getElementById("zone-name").value.trim();
    const a = this._state?.array || {};
    const center = circMean(a.speech_trail_degrees?.length ? a.speech_trail_degrees : a.direction_degrees == null ? [] : [a.direction_degrees]);
    if (!name) { this._setError("Введите название зоны."); return; }
    if (center == null) { this._setError("Направление сейчас неизвестно: скажите что-нибудь со стороны зоны и повторите."); return; }
    const zones = [...(this._state?.room?.zones || []).filter((z) => z.name.toLowerCase() !== name.toLowerCase()), { name, center, width: 40, kind: this._zoneKind }];
    await this._act("room", () => this._api("POST", "room", { zones }));
    this.shadowRoot.getElementById("zone-name").value = "";
  }

  async _loadVoices(force = false) {
    if (this._voicesLoading || (!force && Date.now() - (this._voicesAt || 0) < 5000)) return;
    this._voicesLoading = true;
    try {
      this._voices = await this._api("GET", "voices");
      this._voicesAt = Date.now();
    } catch (e) {
      this._setError(`Не удалось загрузить голоса: ${e?.body?.message || e?.message || e}`);
    } finally {
      this._voicesLoading = false;
    }
  }

  async _voiceStart(who, kind) {
    await this._act("voices", () => this._api("POST", "voices", { action: "start", kind, ...who }));
    this._pendingWho = who;
    this._loadVoices(true);
  }

  _updateVoices(s) {
    this._loadVoices();
    const v = this._voices;
    const r = this.shadowRoot;
    const pos = s.positive || {};
    const sess = pos.session || {};
    const enrolling = pos.active && /^(user|guest)-/.test(sess.speaker || "") && /^enroll_/.test(sess.style || "");
    const live = r.getElementById("voices-live");
    let liveHtml = "";
    if (enrolling && v) {
      const target = v.targets[sess.style] || 5;
      const n = pos.captured || 0;
      const who = (v.users.find((u) => `user-${u.id}` === sess.speaker) || {}).name
        || (v.guests.find((g) => `guest-${g.slug}` === sess.speaker) || {}).name || sess.speaker;
      const phrase = s.phrase?.selected?.phrase || "фразу";
      const body = sess.style === "enroll_phrase"
        ? `<div class="say">Скажите: <span>«${esc(phrase)}»</span></div><div class="small center">пауза 3–5 секунд между повторами</div>`
        : `<ol class="cmds">${v.commands.map((c, i) => `<li class="${i < n ? "done" : i === n ? "next" : ""}">${esc(c)}</li>`).join("")}</ol>
           <div class="small center">читайте по одной, с паузой 3–5 секунд</div>`;
      liveHtml = `
        <div class="pipe running">
          <div class="row between"><div class="big">Записываю голос: ${esc(who)}</div><span class="st running">${sess.style === "enroll_phrase" ? "фраза" : "команды"}</span></div>
          ${body}
          <div class="counter">${n}<small> / ${target}</small></div>
          <button class="btn ${n >= target ? "primary" : ""} wide" id="voices-finish">${n >= target ? "Готово" : "Закончить досрочно"}</button>
        </div>`;
    }
    if (live.dataset.html !== liveHtml) {
      live.dataset.html = liveHtml;
      live.innerHTML = liveHtml;
      live.querySelector("#voices-finish")?.addEventListener("click", () => this._act("positive", async () => {
        await this._api("POST", "positive", { action: "finish" });
        const who = this._pendingWho;
        const style = sess.style;
        this._loadVoices(true);
        if (who && style === "enroll_phrase" && confirm("Фраза записана. Записать 8 команд этим же голосом?")) {
          await this._voiceStart(who, "enroll_commands");
        }
      }));
    }
    const beep = enrolling ? pos.captured : null;
    if (this._voicesCaptured != null && beep != null && beep > this._voicesCaptured) this._click();
    this._voicesCaptured = beep;
    if (!v) return;
    const bar = (have, need) => `<div class="progress thin"><div style="width:${Math.min(100, Math.round((have / need) * 100))}%"></div></div>`;
    const row = (label, sub, clips, whoAttr) => {
      const p = clips.enroll_phrase || 0, c = clips.enroll_commands || 0;
      const done = p >= v.targets.enroll_phrase && c >= v.targets.enroll_commands;
      return `<div class="voice-row">
          <div class="voice-main"><div><b>${esc(label)}</b> <span class="small">${esc(sub)}</span> ${done ? '<span class="st done">голос записан</span>' : ""}</div>
            <div class="small">фраза ${p}/${v.targets.enroll_phrase}</div>${bar(p, v.targets.enroll_phrase)}
            <div class="small">команды ${c}/${v.targets.enroll_commands}</div>${bar(c, v.targets.enroll_commands)}</div>
          <div class="voice-actions">
            <button class="btn small-btn" data-act="enroll_phrase" ${whoAttr} ${enrolling ? "disabled" : ""}>Фраза</button>
            <button class="btn small-btn" data-act="enroll_commands" ${whoAttr} ${enrolling ? "disabled" : ""}>Команды</button>
            ${p + c ? `<button class="btn small-btn" data-act="delete" ${whoAttr}>Удалить голос</button>` : ""}
          </div></div>`;
    };
    const usersHtml = `<h3>Домочадцы (пользователи Home Assistant)</h3>` + v.users.map((u) =>
      row(u.name, u.owner ? "владелец" : u.admin ? "админ" : "", u.clips, `data-user="${esc(u.id)}"`)).join("");
    const guestsHtml = v.guests.length ? v.guests.map((g) =>
      row(g.name, `гость до ${fmtTime(g.expires_at)}`, g.clips, `data-guest="${esc(g.name)}"`)).join("") : "";
    const wire = (el, html) => {
      if (el.dataset.html === html) return;
      el.dataset.html = html;
      el.innerHTML = html;
      el.querySelectorAll("button[data-act]").forEach((b) => b.addEventListener("click", () => {
        const who = b.dataset.user ? { user_id: b.dataset.user } : { guest: b.dataset.guest };
        if (b.dataset.act === "delete") {
          if (confirm("Удалить все записи этого голоса?")) this._act("voices", async () => { await this._api("POST", "voices", { action: "delete", ...who }); this._loadVoices(true); });
        } else {
          this._voiceStart(who, b.dataset.act);
        }
      }));
    };
    wire(r.getElementById("voices-users"), usersHtml);
    wire(r.getElementById("voices-guests"), guestsHtml);
  }

  _updateTrain(s) {
    const t = s.training || {};
    const list = this.shadowRoot.getElementById("train-list");
    const pipes = t.pipelines || [];
    const mins = (sec) => (sec == null ? "" : sec < 90 ? "~1 мин" : sec < 5400 ? `~${Math.round(sec / 60)} мин` : `~${(sec / 3600).toFixed(1)} ч`);
    const icon = { done: "✓", running: "●", failed: "✗", pending: "○" };
    const label = { done: "Готово", running: "Идёт", failed: "Ошибка", pending: "Ожидает" };
    const stale = t.status_age_seconds != null && t.status_age_seconds > 180;
    const html = !pipes.length
      ? `<p class="muted">Обучение сейчас не запущено.</p>`
      : pipes.map((p) => {
        const left = p.stages.filter((st) => st.state !== "done").reduce((a, st) => a + (st.eta_seconds || 0), 0);
        return `
        <div class="pipe ${p.state}">
          <div class="row between"><div class="big">${esc(p.title)}</div><span class="st ${p.state}">${label[p.state] || esc(p.state)}</span></div>
          <div class="progress"><div style="width:${Math.round((p.progress || 0) * 100)}%"></div></div>
          <div class="row between small"><span>${Math.round((p.progress || 0) * 100)}% · этапов готово ${p.stages.filter((st) => st.state === "done").length} из ${p.stages.length}</span>
            <span>${p.state === "running" && left ? `осталось ${mins(left)}${p.stages.some((st) => st.state !== "done" && st.estimate) ? " (оценка)" : ""}` : ""}</span></div>
          <div class="stages">${p.stages.map((st) => `
            <div class="stage ${st.state}">
              <span class="ic">${icon[st.state] || "○"}</span>
              <div class="stage-main"><div>${esc(st.title)}</div>
                ${st.state === "running" ? `<div class="progress thin"><div style="width:${Math.round((st.progress || 0) * 100)}%"></div></div>
                  <div class="small">${st.progress != null ? `${Math.round(st.progress * 100)}%` : "идёт"}${st.detail ? ` · ${esc(st.detail)}` : ""}${st.eta_seconds ? ` · ещё ${mins(st.eta_seconds)}` : ""}${st.estimate ? " · оценка по времени" : ""}</div>` : ""}
                ${st.state === "done" && st.finished_at ? `<div class="small">${fmtTime(st.finished_at)}</div>` : ""}
              </div>
            </div>`).join("")}
          </div>
          ${p.summary ? `<h3>Результаты приёмки</h3><pre class="pre">${esc(p.summary)}</pre>` : ""}
          ${p.log_tail?.length ? `<details class="note"><summary>Журнал</summary><pre class="pre">${esc(p.log_tail.join("\n"))}</pre></details>` : ""}
        </div>`;
      }).join("") + (stale ? `<div class="note warn">Статус не обновлялся ${Math.round(t.status_age_seconds / 60)} мин: проверьте cron pipeline_status.py.</div>` : "");
    if (list.dataset.html !== html) {
      const open = [...list.querySelectorAll("details")].map((d) => d.open);
      list.dataset.html = html;
      list.innerHTML = html;
      list.querySelectorAll("details").forEach((d, i) => (d.open = !!open[i]));
    }
  }

  _updateNoise(s) {
    const n = s.noise || {};
    const rl = n.raw_live || {};
    const r = this.shadowRoot;
    const labels = { recording: "Идёт запись шума", stopped: "Запись остановлена", complete: "Запись завершена", idle: "Сессии нет" };
    r.getElementById("noise-state").textContent = labels[n.state] || "Нет данных";
    r.getElementById("noise-bar").style.width = `${Math.round((n.progress || 0) * 100)}%`;
    r.getElementById("noise-hours").textContent = `${fmtHours(rl.hours_since_start)} из ${n.target_hours ?? 168} ч (${Math.round((n.progress || 0) * 100)}%)`;
    r.getElementById("noise-eta").textContent = n.state === "recording" ? `осталось ${fmtEta(n.eta_hours)}` : "";
    const last = (rl.recent_segments || []).slice(-1)[0];
    const kv = [
      ["Начата", fmtTime(n.started_at)],
      ["Последний сегмент", last ? `${fmtTime(rl.latest_mtime)} · пик ${last.peak} · ${last.rms_dbfs} dBFS` : "—"],
      ["Цифровая тишина (не записана)", fmtHours(rl.silent_hours_since_start)],
      ["Свободно на диске", n.disk ? `${n.disk.free_gb} ГБ (пауза ниже 30 ГБ)` : "—"],
      ["Статус обновлён", n.status_age_seconds == null ? "—" : `${Math.round(n.status_age_seconds / 60)} мин назад`],
    ];
    if (rl.recent_all_silent && n.state === "recording") kv.unshift(["⚠ Внимание", "последние сегменты — цифровая тишина"]);
    r.getElementById("noise-kv").innerHTML = kv.map(([k, v]) => `<span>${esc(k)}</span><b>${esc(v)}</b>`).join("");
    const busy = this._busy.has("noise");
    const box = r.getElementById("noise-actions");
    const html = n.state === "recording"
      ? `<button class="btn" id="noise-stop" ${busy ? "disabled" : ""}>Остановить</button>`
      : `<button class="btn primary" id="noise-start" ${busy ? "disabled" : ""}>Начать запись шума (7 дней)</button>`;
    if (box.dataset.html !== html) {
      box.dataset.html = html;
      box.innerHTML = html;
      box.querySelector("#noise-start")?.addEventListener("click", () => this._act("noise", () => this._api("POST", "noise", { action: "start" })));
      box.querySelector("#noise-stop")?.addEventListener("click", () => {
        if (confirm("Остановить запись фонового шума? Уже записанное сохранится.")) this._act("noise", () => this._api("POST", "noise", { action: "stop" }));
      });
    }
  }

  _updatePhrase(s) {
    const r = this.shadowRoot;
    const p = s.phrase || {};
    const sel = p.selected;
    const selHtml = sel
      ? `<div class="small">Выбранная фраза</div><div class="phrase-big">«${esc(sel.phrase)}»</div>
         <div class="small">выбрана ${fmtTime(sel.selected_at)}${sel.by ? ` · ${esc(sel.by)}` : ""} · <a href="#" id="phrase-unselect">отменить выбор</a></div>`
      : `<div class="phrase-big muted">Фраза ещё не выбрана</div><div class="small">Проверьте несколько вариантов и выберите лучший.</div>`;
    const box = r.getElementById("phrase-selected");
    if (box.dataset.html !== selHtml) {
      box.dataset.html = selHtml;
      box.innerHTML = selHtml;
      box.querySelector("#phrase-unselect")?.addEventListener("click", (e) => {
        e.preventDefault();
        if (confirm("Отменить выбор фразы?")) this._act("phrase", () => this._api("POST", "phrase", { action: "unselect" }));
      });
    }
    const rows = (p.candidates || []).map((c) => {
      const [vl, vc] = VERDICTS[c.verdict] || VERDICTS.unknown;
      const isSel = sel && sel.phrase.toLowerCase() === (c.phrase || "").toLowerCase();
      return `<tr><td><b>${esc(c.phrase)}</b><div class="small">${c.syllables} слог. · ~${c.phonemes_approx} звуков</div></td>
        <td><span class="verdict" style="--vc:${vc}">${vl}</span></td>
        <td class="num">${c.near_per_hour ?? "—"}<div class="small">похожих/ч</div></td>
        <td class="actions">${isSel ? `<span class="chip ok">выбрана</span>` : `<button class="btn small-btn" data-select="${esc(c.phrase)}">Выбрать</button>`}
          <button class="icon-btn" title="Убрать" data-forget="${esc(c.phrase)}">✕</button></td></tr>`;
    }).join("");
    const table = rows ? `<table class="tbl"><tbody>${rows}</tbody></table>` : `<div class="small">Пока ничего не проверено.</div>`;
    const tbox = r.getElementById("phrase-table");
    if (tbox.dataset.html !== table) {
      tbox.dataset.html = table;
      tbox.innerHTML = table;
      tbox.querySelectorAll("[data-select]").forEach((b) => b.addEventListener("click", () => {
        if (confirm(`Выбрать «${b.dataset.select}»? С ней будут записи и обучение модели.`)) this._act("phrase", () => this._api("POST", "phrase", { action: "select", phrase: b.dataset.select }));
      }));
      tbox.querySelectorAll("[data-forget]").forEach((b) => b.addEventListener("click", () => this._act("phrase", () => this._api("POST", "phrase", { action: "forget", phrase: b.dataset.forget }))));
    }
    const t = p.transcripts || {};
    r.getElementById("phrase-corpus").textContent = t.hours
      ? `Проверка идёт по ${t.hours} ч расшифрованных домашних записей (${t.utterances ?? "?"} фраз, обновлено ${fmtTime(t.updated_at)}). Расшифровка новых записей шума добавляется каждую ночь.`
      : "Расшифровка домашних записей ещё не загружена.";
  }

  async _checkPhrase() {
    const input = this.shadowRoot.getElementById("phrase-input");
    const phrase = input.value.trim();
    if (!phrase) return;
    const out = this.shadowRoot.getElementById("phrase-result");
    out.innerHTML = `<div class="small">Проверяю «${esc(phrase)}» по домашней расшифровке…</div>`;
    await this._act("phrase-check", async () => {
      const res = await this._api("POST", "phrase", { action: "screen", phrase });
      const [vl, vc] = VERDICTS[res.verdict] || VERDICTS.unknown;
      const ex = (res.examples || []).slice(0, 5).map((e) => `<li><b>${esc(e.match)}</b> — «${esc(e.context)}»</li>`).join("");
      out.innerHTML = `<div class="result" style="--vc:${vc}">
        <div class="row between"><b>«${esc(res.phrase)}»</b><span class="verdict" style="--vc:${vc}">${vl}</span></div>
        <div class="small">${res.syllables} слог. · ~${res.phonemes_approx} звуков · похожих по звучанию: ${res.near_hits} за ${res.hours} ч (${res.near_per_hour}/ч)</div>
        ${ex ? `<div class="small">Где звучало похоже:</div><ul class="examples">${ex}</ul>` : `<div class="small">Похожих по звучанию слов в домашних записях не найдено.</div>`}
      </div>`;
      input.value = "";
    });
  }

  _updateRecord(s) {
    const r = this.shadowRoot;
    const sel = s.phrase?.selected;
    const pos = s.positive || {};
    r.getElementById("rec-need-phrase").hidden = !!sel;
    r.getElementById("rec-setup").hidden = !!pos.active;
    r.getElementById("rec-live").hidden = !pos.active;
    r.getElementById("rec-start").disabled = !sel || this._busy.has("positive");
    r.getElementById("rec-finish").disabled = this._busy.has("positive");
    const speakers = Object.keys(s.review?.by_speaker || {});
    const dl = r.getElementById("rec-speakers");
    const dlHtml = speakers.map((x) => `<option value="${esc(x)}">`).join("");
    if (dl.dataset.html !== dlHtml) { dl.dataset.html = dlHtml; dl.innerHTML = dlHtml; }
    if (pos.active) {
      const target = Number(pos.session?.expected_attempts || 0);
      const now = Number(pos.captured || 0);
      r.getElementById("rec-phrase").textContent = pos.session?.phrase || sel?.phrase || "";
      r.getElementById("rec-count-now").textContent = now;
      r.getElementById("rec-count-target").textContent = target || "∞";
      r.getElementById("rec-bar").style.width = target ? `${Math.min(100, (now / target) * 100)}%` : "0%";
      const lvl = s.array?.level_dbfs;
      r.getElementById("rec-lvl").style.width = `${lvl == null ? 0 : Math.max(0, Math.min(100, ((lvl + 80) / 80) * 100))}%`;
      if (this._lastCaptured != null && now > this._lastCaptured) this._click();
      this._lastCaptured = now;
    } else {
      this._lastCaptured = null;
    }
    const bySpeaker = s.review?.by_speaker || {};
    const by = s.review?.by_status || {};
    r.getElementById("rec-summary").innerHTML = `Всего клипов: ${s.review?.total ?? 0} (ожидают ${by.pending || 0}, подтверждено ${by.confirmed || 0}, отклонено ${by.rejected || 0})` +
      (Object.keys(bySpeaker).length ? `<br>${Object.entries(bySpeaker).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ")}` : "");
  }

  async _startPositive() {
    const speaker = (this._setup.speaker || "").trim();
    if (!speaker) {
      this._setError("Укажите, кто говорит.");
      this.shadowRoot.getElementById("rec-speaker").focus();
      return;
    }
    this._unlockAudio();
    await this._act("positive", () => this._api("POST", "positive", {
      action: "start", speaker, style: this._setup.style, location: this._setup.location, expected: this._setup.expected,
    }));
  }

  // ------------------------------------------------------------------ review
  _filtered() {
    const f = this._filter;
    return this._clips.filter((c) => f === "all" || (f === "active" ? c.status !== "rejected" : c.status === f));
  }

  _updateReviewHeader() {
    const list = this._filtered();
    this.shadowRoot.getElementById("rv-count").textContent = `${list.length} клипов в фильтре · всего ${this._clips.length}`;
    this.shadowRoot.getElementById("rv-play").textContent = this._playlist ? "⏸ Пауза" : "▶ Слушать подряд";
  }

  _renderReviewList() {
    const box = this.shadowRoot?.getElementById("rv-list");
    if (!box) return;
    const list = this._filtered().slice(0, this._shown);
    const ids = list.map((c) => c.id).join(",");
    if (box.dataset.ids === ids) {
      list.forEach((c) => this._paintRow(c));  // statuses only; keeps scroll and focus stable
    } else {
      box.dataset.ids = ids;
      box.innerHTML = list.length ? list.map((c) => this._rowHtml(c)).join("") : `<div class="small">Записей нет. Они появятся после сессии во вкладке «Запись».</div>`;
      box.querySelectorAll(".clip").forEach((row) => {
        const id = row.dataset.id;
        row.querySelector(".play").addEventListener("click", () => this._play(id, false));
        row.querySelector(".ok-btn").addEventListener("click", () => this._review(id, "confirmed"));
        row.querySelector(".no-btn").addEventListener("click", () => this._review(id, "rejected"));
      });
    }
    this._updateReviewHeader();
  }

  _rowHtml(c) {
    const meta = [c.speaker, (STYLES.find(([v]) => v === c.style) || [0, c.style])[1], (LOCATIONS.find(([v]) => v === c.location) || [0, c.location])[1]].filter(Boolean).map(esc).join(" · ");
    return `<div class="clip ${c.status}${this._playing === c.id ? " playing" : ""}" data-id="${c.id}">
      <button class="icon-btn play" title="Слушать">▶</button>
      <div class="clip-main"><div><b>${esc(c.phrase || "")}</b> <span class="small">${fmtTime(c.created_at)}</span></div>
        <div class="small">${meta} · ${Number(c.duration || 0).toFixed(1)} с${c.level_max_dbfs != null ? ` · пик ${c.level_max_dbfs} dBFS` : ""}${c.doa_degrees != null ? ` · ${c.doa_degrees}°` : ""}</div></div>
      <span class="status">${{ pending: "ожидает", confirmed: "✓ подтверждён", rejected: "✕ отклонён" }[c.status] || ""}</span>
      <button class="icon-btn ok-btn" title="Это фраза, хорошая запись">✓</button>
      <button class="icon-btn no-btn" title="Не фраза или плохая запись">✕</button>
    </div>`;
  }

  _paintRow(c) {
    const row = this.shadowRoot.querySelector(`.clip[data-id="${c.id}"]`);
    if (!row) return;
    row.className = `clip ${c.status}${this._playing === c.id ? " playing" : ""}`;
    row.querySelector(".status").textContent = { pending: "ожидает", confirmed: "✓ подтверждён", rejected: "✕ отклонён" }[c.status] || "";
  }

  async _review(id, status) {
    const clip = this._clips.find((c) => c.id === id);
    if (!clip) return;
    const next = clip.status === status ? "pending" : status;
    const prev = clip.status;
    clip.status = next;
    this._renderReviewList();
    try {
      await this._api("POST", "review", { id, status: next });
    } catch (e) {
      clip.status = prev;
      this._renderReviewList();
      this._setError(`Не сохранилось: ${e?.message || e}`);
    }
  }

  async _play(id, continuePlaylist) {
    this._unlockAudio();
    if (this._playing === id && this._audio && !this._audio.paused && !continuePlaylist) {
      this._stopAudio();
      return;
    }
    this._stopAudio(false);
    this._playlist = continuePlaylist;
    const clip = this._clips.find((c) => c.id === id);
    if (!clip) return;
    const { path } = await this._hass.callWS({ type: "auth/sign_path", path: `/api/wakeword_studio/audio/${id}`, expires: 600 });
    this._audio = new Audio(path);
    this._playing = id;
    this._markPlaying();
    this._audio.addEventListener("ended", () => this._next(id));
    this._audio.addEventListener("error", () => this._next(id));
    try { await this._audio.play(); } catch (e) { this._setError(`Не удалось воспроизвести: ${e?.message || e}`); }
  }

  _next(id) {
    if (!this._playlist) { this._stopAudio(); return; }
    const list = this._filtered();
    const i = list.findIndex((c) => c.id === id);
    const nxt = list[i + 1];
    if (!nxt) { this._stopAudio(); return; }
    if (i + 1 >= this._shown) { this._shown += PAGE; this._renderReviewList(); }
    this._gapTimer = setTimeout(() => this._play(nxt.id, true), 500);
  }

  _togglePlaylist() {
    if (this._playlist) { this._stopAudio(); return; }
    const list = this._filtered();
    const start = list.find((c) => c.status === "pending") || list[0];
    if (start) this._play(start.id, true);
  }

  _stopAudio(repaint = true) {
    clearTimeout(this._gapTimer);
    if (this._audio) { this._audio.pause(); this._audio = null; }
    this._playing = null;
    if (repaint) { this._playlist = false; this._markPlaying(); this._updateReviewHeader?.(); }
  }

  _markPlaying() {
    this.shadowRoot?.querySelectorAll(".clip").forEach((row) => row.classList.toggle("playing", row.dataset.id === this._playing));
    const row = this._playing && this.shadowRoot.querySelector(`.clip[data-id="${this._playing}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ------------------------------------------------------------------ sound
  _unlockAudio() {
    if (!this._ctx) {
      try { this._ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch { this._ctx = null; }
    }
    this._ctx?.resume?.();
  }

  _click() {
    const ctx = this._ctx;
    if (!ctx) return;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 1320;
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.12);
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.13);
  }
}

const CSS = `
:host { display:block; }
ha-card { padding: 16px; }
.head { display:flex; flex-wrap:wrap; gap:8px; align-items:center; justify-content:space-between; }
.title { font-size: 1.35em; font-weight: 600; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chip { font-size:.8em; padding:3px 9px; border-radius:12px; background: var(--secondary-background-color, #eee); color: var(--secondary-text-color); }
.chip.ok { background: color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); color: var(--success-color, #2e7d32); }
.chip.bad { background: color-mix(in srgb, var(--error-color, #e53935) 18%, transparent); color: var(--error-color, #c62828); }
.tabs { display:flex; gap:2px; margin:14px 0 12px; border-bottom:1px solid var(--divider-color); }
.tab { flex:1 1 0; min-width:0; display:flex; flex-direction:column; align-items:center; gap:2px; padding:8px 6px; border:0; background:none; cursor:pointer;
  color: var(--secondary-text-color); border-bottom:3px solid transparent; font: inherit; font-size:.85em; }
.tab svg { width:20px; height:20px; fill: currentColor; }
.tab span { font-size:.78em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }
.zone-lbl { font-size:11px; font-weight:600; text-anchor:middle; }
.zone-row { display:flex; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid var(--divider-color); }
.zone-row .small { flex:1; }
.zone-dot { width:10px; height:10px; border-radius:50%; flex:none; }
.tab.on { color: var(--primary-color); border-bottom-color: var(--primary-color); }
section[hidden] { display:none; }
.err { background: color-mix(in srgb, var(--error-color, #e53935) 14%, transparent); color: var(--error-color, #c62828); padding:8px 12px; border-radius:8px; margin-bottom:10px; }
.grid2 { display:grid; grid-template-columns: minmax(200px, 300px) 1fr; gap:18px; align-items:center; }
@media (max-width: 620px) { .grid2 { grid-template-columns: 1fr; } }
.compass-wrap svg { width:100%; max-width:300px; display:block; margin:auto; }
.ring { fill:none; stroke: var(--divider-color); stroke-width:1.5; }
.tick { stroke: var(--secondary-text-color); stroke-width:1.2; }
.lbl-deg { font-size:9px; fill: var(--secondary-text-color); text-anchor: middle; }
.heat { fill: var(--warning-color, #fb8c00); }
.needle { stroke: var(--primary-color); stroke-width:5; stroke-linecap:round; transition: transform .25s ease; }
.needle.speech { stroke: var(--success-color, #43a047); }
.hub { fill: var(--card-background-color, #fff); stroke: var(--divider-color); stroke-width:2; transition: fill .2s; }
.hub.speech { fill: color-mix(in srgb, var(--success-color, #43a047) 25%, var(--card-background-color, #fff)); }
.hub-text { font-size:13px; text-anchor:middle; fill: var(--primary-text-color); }
.dot { fill: var(--success-color, #43a047); }
.stack { display:flex; flex-direction:column; gap:6px; }
.kv, .row.between { display:flex; justify-content:space-between; gap:12px; align-items:center; }
.kv span { color: var(--secondary-text-color); }
.meter { position:relative; height:12px; border-radius:6px; background: var(--secondary-background-color, #eee); overflow:hidden; }
.meter > div:first-child { height:100%; width:0; background: linear-gradient(90deg, var(--success-color, #43a047), var(--warning-color, #fb8c00) 80%, var(--error-color, #e53935)); transition: width .15s linear; }
.meter .peak { position:absolute; top:0; width:2px; height:100%; background: var(--primary-text-color); opacity:.6; }
.hint, .small { color: var(--secondary-text-color); font-size:.86em; }
.note { margin-top:12px; padding:10px 12px; border-radius:8px; background: var(--secondary-background-color, #f5f5f5); font-size:.9em; line-height:1.4; }
.note.warn { background: color-mix(in srgb, var(--warning-color, #fb8c00) 16%, transparent); }
.note ul { margin:6px 0 0; padding-left:20px; }
.big { font-size:1.2em; font-weight:600; }
.progress { height:10px; border-radius:5px; background: var(--secondary-background-color, #eee); overflow:hidden; margin:10px 0 4px; }
.progress > div { height:100%; width:0; background: var(--primary-color); transition: width .4s; }
.grid-kv { display:grid; grid-template-columns: max-content 1fr; gap:6px 14px; margin-top:12px; font-size:.92em; }
.grid-kv span { color: var(--secondary-text-color); }
.row { display:flex; gap:8px; align-items:center; margin:8px 0; flex-wrap:wrap; }
input { flex:1; min-width:180px; padding:10px 12px; border-radius:8px; border:1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }
.btn { padding:9px 16px; border-radius:18px; border:1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); cursor:pointer; font: inherit; }
.btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
.btn:disabled { opacity:.5; cursor:default; }
.btn.wide { width:100%; margin-top:14px; padding:12px; font-size:1.05em; }
.small-btn { padding:5px 12px; font-size:.85em; }
.icon-btn { width:34px; height:34px; border-radius:50%; border:1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); cursor:pointer; font-size:14px; flex:none; }
.selected { padding:12px 14px; border-radius:10px; border:1px solid var(--divider-color); margin-bottom:6px; }
.phrase-big { font-size:1.5em; font-weight:600; margin:2px 0; }
.muted { color: var(--secondary-text-color); }
.verdict { display:inline-block; padding:2px 10px; border-radius:10px; font-size:.82em; color: var(--vc); background: color-mix(in srgb, var(--vc) 15%, transparent); }
.result { border-left:4px solid var(--vc); padding:8px 12px; margin:8px 0; background: var(--secondary-background-color, #f7f7f7); border-radius:6px; }
.examples { margin:4px 0 0; padding-left:18px; font-size:.86em; }
h3 { font-size:1em; margin:18px 0 6px; }
.tbl { width:100%; border-collapse: collapse; }
.tbl td { padding:8px 6px; border-bottom:1px solid var(--divider-color); vertical-align: middle; }
.tbl .num { text-align:right; }
.tbl .actions { text-align:right; white-space:nowrap; }
.lbl { display:block; margin:12px 0 4px; font-size:.86em; color: var(--secondary-text-color); }
.seg { display:flex; flex-wrap:wrap; gap:6px; }
.seg button { padding:7px 12px; border-radius:16px; border:1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); cursor:pointer; font: inherit; font-size:.9em; }
.seg button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
.say { font-size:1.4em; text-align:center; margin-top:6px; }
.say span { font-weight:700; }
.counter { text-align:center; font-size:3.2em; font-weight:700; line-height:1.1; margin:10px 0 0; }
.counter small { font-size:.4em; color: var(--secondary-text-color); font-weight:400; }
.list { display:flex; flex-direction:column; gap:6px; margin-top:10px; }
.clip { display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:10px; border:1px solid var(--divider-color); }
.clip.playing { border-color: var(--primary-color); box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 30%, transparent); }
.clip.confirmed { background: color-mix(in srgb, var(--success-color, #43a047) 8%, transparent); }
.clip.rejected { opacity:.55; }
.clip-main { flex:1; min-width:0; }
.clip .status { font-size:.8em; color: var(--secondary-text-color); white-space:nowrap; }
.clip.confirmed .ok-btn { background: var(--success-color, #43a047); color:#fff; border-color: transparent; }
.clip.rejected .no-btn { background: var(--error-color, #e53935); color:#fff; border-color: transparent; }
.sentinel { height: 24px; }
a { color: var(--primary-color); }
.voice-row { display:flex; gap:12px; align-items:center; padding:10px 0; border-bottom:1px solid var(--divider-color); flex-wrap:wrap; }
.voice-main { flex:1; min-width:200px; }
.voice-actions { display:flex; gap:6px; flex-wrap:wrap; }
.cmds { margin:8px 0; padding-left:22px; line-height:1.7; }
.cmds li.done { color: var(--secondary-text-color); text-decoration: line-through; }
.cmds li.next { font-weight:700; font-size:1.15em; color: var(--primary-color); }
.center { text-align:center; }
.pipe { padding:12px 14px; border-radius:10px; border:1px solid var(--divider-color); margin-bottom:12px; }
.pipe.failed { border-color: var(--error-color, #e53935); }
.st { font-size:.82em; padding:2px 10px; border-radius:10px; background: var(--secondary-background-color, #eee); }
.st.running { background: color-mix(in srgb, var(--primary-color) 18%, transparent); color: var(--primary-color); }
.st.done { background: color-mix(in srgb, var(--success-color, #43a047) 18%, transparent); color: var(--success-color, #2e7d32); }
.st.failed { background: color-mix(in srgb, var(--error-color, #e53935) 18%, transparent); color: var(--error-color, #c62828); }
.stages { display:flex; flex-direction:column; gap:2px; margin-top:10px; }
.stage { display:flex; gap:10px; padding:6px 0; border-bottom:1px solid var(--divider-color); }
.stage:last-child { border-bottom:0; }
.stage .ic { width:18px; text-align:center; flex:none; color: var(--secondary-text-color); }
.stage.done .ic { color: var(--success-color, #43a047); }
.stage.running .ic { color: var(--primary-color); }
.stage.failed .ic { color: var(--error-color, #e53935); }
.stage.pending { color: var(--secondary-text-color); }
.stage-main { flex:1; min-width:0; }
.progress.thin { height:6px; margin:6px 0 2px; }
.pre { white-space:pre-wrap; overflow-x:auto; font-size:.8em; line-height:1.35; margin:6px 0 0; font-family: var(--code-font-family, monospace); }
`;

if (!customElements.get("wakeword-studio-card")) {
  customElements.define("wakeword-studio-card", WakewordStudioCard);
}
window.customCards = window.customCards || [];
window.customCards.push({ type: "wakeword-studio-card", name: "Wakeword Studio", description: "Микрофон, запись шума, выбор фразы, запись и разметка" });
