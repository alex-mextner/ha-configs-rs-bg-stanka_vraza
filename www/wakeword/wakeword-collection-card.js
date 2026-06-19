const WAKEWORD_PLAN = [
  {
    name: "Owner quiet warmup",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "normal",
    location: "near_satellite_1m_quiet",
    attempts: 30,
    cue: "Обычный голос рядом с микрофоном.",
  },
  {
    name: "Owner short phrase",
    phrase: "Милош",
    speaker: "speaker_1_owner",
    style: "normal",
    location: "near_satellite_1m_quiet",
    attempts: 20,
    cue: "Короткая фраза без спешки.",
  },
  {
    name: "Sofa distance",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "far",
    location: "sofa_3m_quiet",
    attempts: 20,
    cue: "С дивана или с расстояния около трех метров.",
  },
  {
    name: "Whisper",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "whisper",
    location: "near_satellite_1m_quiet",
    attempts: 10,
    cue: "Шепотом, но разборчиво.",
  },
  {
    name: "Loud voice",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "loud",
    location: "near_satellite_1m_quiet",
    attempts: 10,
    cue: "Громко, без крика в микрофон.",
  },
  {
    name: "Tired voice",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "tired",
    location: "sofa_3m_quiet",
    attempts: 10,
    cue: "Низко, сонно, как вечером.",
  },
  {
    name: "Hallway and doorway",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "other_room",
    location: "doorway",
    attempts: 20,
    cue: "Из дверного проема или коридора.",
  },
  {
    name: "TV or music noise",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "normal",
    location: "tv_or_music_noise",
    attempts: 20,
    cue: "На фоне ТВ или музыки.",
  },
  {
    name: "Kitchen noise",
    phrase: "эй Милош",
    speaker: "speaker_1_owner",
    style: "normal",
    location: "kitchen_noise",
    attempts: 20,
    cue: "С кухни или рядом с бытовым шумом.",
  },
  {
    name: "Second speaker",
    phrase: "эй Милош",
    speaker: "speaker_2",
    style: "normal",
    location: "near_satellite_1m_quiet",
    attempts: 30,
    cue: "Другой человек, обычный голос.",
  },
  {
    name: "Third or guest speaker",
    phrase: "эй Милош",
    speaker: "speaker_3",
    style: "normal",
    location: "sofa_3m_quiet",
    attempts: 30,
    cue: "Еще один голос, лучше с другого места.",
  },
  {
    name: "Guest noisy mix",
    phrase: "эй Милош",
    speaker: "guest",
    style: "moving",
    location: "conversation_noise",
    attempts: 20,
    cue: "Гость, движение или разговоры на фоне.",
  },
];

const LABELS = {
  phrase: {
    "эй Милош": "эй Милош",
    "Милош": "Милош",
  },
  speaker: {
    speaker_1_owner: "Владелец",
    speaker_2: "Человек 2",
    speaker_3: "Человек 3",
    guest: "Гость",
  },
  style: {
    normal: "Обычный",
    whisper: "Шепот",
    loud: "Громко",
    far: "Далеко",
    other_room: "Другая комната",
    moving: "В движении",
    tired: "Усталый голос",
  },
  location: {
    near_satellite_1m_quiet: "1 м, тихо",
    sofa_3m_quiet: "Диван 3 м",
    kitchen_noise: "Кухня/шум",
    hallway: "Коридор",
    doorway: "Дверной проем",
    tv_or_music_noise: "ТВ/музыка",
    conversation_noise: "Разговоры",
  },
};

const ROOM_POINTS = [
  { id: "near_satellite_1m_quiet", label: "1 м", x: 49, y: 52 },
  { id: "sofa_3m_quiet", label: "Диван", x: 18, y: 68 },
  { id: "kitchen_noise", label: "Кухня", x: 80, y: 26 },
  { id: "hallway", label: "Коридор", x: 83, y: 74 },
  { id: "doorway", label: "Проем", x: 52, y: 16 },
  { id: "tv_or_music_noise", label: "ТВ", x: 19, y: 25 },
  { id: "conversation_noise", label: "Разговор", x: 67, y: 68 },
];

class WakewordCollectionCard extends HTMLElement {
  setConfig(config) {
    this.config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.render();
    }
    this.update();
  }

  getCardSize() {
    return 12;
  }

  connectedCallback() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.render();
    }
  }

  state(entityId) {
    return this._hass?.states?.[entityId];
  }

  value(entityId, fallback = "") {
    const state = this.state(entityId)?.state;
    return state === undefined || state === "unknown" || state === "unavailable" ? fallback : state;
  }

  attr(entityId, name, fallback = undefined) {
    const value = this.state(entityId)?.attributes?.[name];
    return value === undefined || value === null ? fallback : value;
  }

  async call(domain, service, data = {}) {
    await this._hass.callService(domain, service, data);
  }

  async setSelect(entityId, option) {
    await this.call("input_select", "select_option", { entity_id: entityId, option });
  }

  async setNumber(entityId, value) {
    await this.call("input_number", "set_value", { entity_id: entityId, value: Number(value) });
  }

  async setText(entityId, value) {
    await this.call("input_text", "set_value", { entity_id: entityId, value: String(value || "") });
  }

  async applyStep(step) {
    if (!step) return;
    await this.setSelect("input_select.wakeword_collection_phrase", step.phrase);
    await this.setSelect("input_select.wakeword_collection_speaker", step.speaker);
    await this.setSelect("input_select.wakeword_collection_style", step.style);
    await this.setSelect("input_select.wakeword_collection_location", step.location);
    await this.setNumber("input_number.wakeword_collection_expected_attempts", step.attempts);
    this.playSound("click");
  }

  async selectPlanStep(index) {
    const clamped = Math.max(0, Math.min(WAKEWORD_PLAN.length - 1, index));
    await this.setNumber("input_number.wakeword_collection_plan_step", clamped + 1);
    await this.applyStep(WAKEWORD_PLAN[clamped]);
  }

  async startSession() {
    this.playSound("start");
    await this.call("script", "turn_on", { entity_id: "script.wakeword_collection_start" });
  }

  async finishSession() {
    this.playSound("success");
    await this.call("script", "turn_on", { entity_id: "script.wakeword_collection_finish" });
  }

  async refreshSession() {
    await this.call("homeassistant", "update_entity", { entity_id: "sensor.wakeword_positive_session" });
  }

  soundEnabled() {
    return localStorage.getItem("wakewordCollectionSound") !== "off";
  }

  setSoundEnabled(enabled) {
    localStorage.setItem("wakewordCollectionSound", enabled ? "on" : "off");
    if (enabled) this.playSound("success");
    this.update();
  }

  async playSound(kind) {
    if (!this.soundEnabled()) return;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;
      this.audioContext = this.audioContext || new AudioContext();
      const ctx = this.audioContext;
      if (ctx.state === "suspended") await ctx.resume();
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      const now = ctx.currentTime;
      const sequence = {
        click: [520, 680],
        start: [440, 660, 880],
        success: [660, 880, 1040],
        warn: [220, 180],
      }[kind] || [440];
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(sequence[0], now);
      sequence.forEach((freq, index) => {
        oscillator.frequency.setValueAtTime(freq, now + index * 0.075);
      });
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.09, now + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + Math.max(0.14, sequence.length * 0.08));
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start(now);
      oscillator.stop(now + Math.max(0.16, sequence.length * 0.09));
    } catch (_err) {
      // Browser audio is best-effort only.
    }
  }

  async toggleMicMonitor() {
    if (this.micStream) {
      this.stopMicMonitor();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      this.micAudioContext = new AudioContext();
      const source = this.micAudioContext.createMediaStreamSource(stream);
      const analyser = this.micAudioContext.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      this.micStream = stream;
      this.micAnalyser = analyser;
      this.micBuffer = new Float32Array(analyser.fftSize);
      this.monitorMic();
    } catch (error) {
      this.micError = error?.message || String(error);
      this.playSound("warn");
      this.update();
    }
  }

  stopMicMonitor() {
    if (this.micFrame) cancelAnimationFrame(this.micFrame);
    this.micStream?.getTracks().forEach((track) => track.stop());
    this.micAudioContext?.close();
    this.micStream = undefined;
    this.micAnalyser = undefined;
    this.micAudioContext = undefined;
    this.micLevel = 0;
    this.micDb = -90;
    this.update();
  }

  monitorMic() {
    if (!this.micAnalyser) return;
    this.micAnalyser.getFloatTimeDomainData(this.micBuffer);
    let sum = 0;
    for (const sample of this.micBuffer) sum += sample * sample;
    const rms = Math.sqrt(sum / this.micBuffer.length);
    this.micLevel = Math.min(1, rms * 8);
    this.micDb = rms > 0 ? Math.max(-90, 20 * Math.log10(rms)) : -90;
    this.updateMicOnly();
    this.micFrame = requestAnimationFrame(() => this.monitorMic());
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          color: var(--primary-text-color);
          --ww-ink: #20242c;
          --ww-muted: #687385;
          --ww-line: rgba(68, 78, 97, 0.18);
          --ww-panel: var(--card-background-color, #ffffff);
          --ww-soft: rgba(28, 132, 126, 0.10);
          --ww-good: #0f8f64;
          --ww-teal: #147c8c;
          --ww-warn: #b36b00;
          --ww-coral: #c84d42;
        }
        ha-card {
          overflow: hidden;
          border-radius: 8px;
          border: 1px solid var(--ww-line);
          background:
            linear-gradient(120deg, rgba(20, 124, 140, 0.10), rgba(15, 143, 100, 0.08) 42%, rgba(200, 77, 66, 0.06)),
            var(--ww-panel);
        }
        .wrap { padding: 18px; }
        .top {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 14px;
          align-items: start;
          margin-bottom: 16px;
        }
        .title {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
        }
        .title ha-icon { color: var(--ww-teal); }
        h1 {
          margin: 0;
          font-size: 24px;
          line-height: 1.1;
          letter-spacing: 0;
          color: var(--ww-ink);
        }
        .subtitle {
          margin-top: 7px;
          color: var(--ww-muted);
          font-size: 13px;
          line-height: 1.35;
        }
        .status {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 7px 10px;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.72);
          border: 1px solid var(--ww-line);
          font-weight: 700;
          font-size: 13px;
          white-space: nowrap;
        }
        .dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--ww-muted);
        }
        .status.active .dot {
          background: var(--ww-coral);
          box-shadow: 0 0 0 5px rgba(200, 77, 66, 0.16);
        }
        .main {
          display: grid;
          grid-template-columns: minmax(320px, 1.2fr) minmax(300px, 0.8fr);
          gap: 16px;
        }
        .panel {
          background: rgba(255, 255, 255, 0.78);
          border: 1px solid var(--ww-line);
          border-radius: 8px;
          padding: 14px;
          min-width: 0;
        }
        .hero {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 132px;
          gap: 16px;
          align-items: center;
          margin-bottom: 14px;
        }
        .eyebrow {
          color: var(--ww-muted);
          text-transform: uppercase;
          font-size: 11px;
          font-weight: 800;
          letter-spacing: 0.08em;
        }
        .phrase {
          margin-top: 6px;
          font-size: 48px;
          line-height: 1;
          font-weight: 850;
          color: var(--ww-ink);
          overflow-wrap: anywhere;
        }
        .cue {
          margin-top: 9px;
          font-size: 14px;
          color: var(--ww-muted);
          line-height: 1.35;
        }
        .ring {
          position: relative;
          width: 126px;
          height: 126px;
        }
        .ring svg {
          width: 126px;
          height: 126px;
          transform: rotate(-90deg);
        }
        .ring .bg { stroke: rgba(104, 115, 133, 0.18); }
        .ring .fg {
          stroke: var(--ww-good);
          stroke-linecap: round;
          transition: stroke-dashoffset 0.35s ease;
        }
        .ring-label {
          position: absolute;
          inset: 0;
          display: grid;
          place-items: center;
          text-align: center;
          font-weight: 850;
          color: var(--ww-ink);
        }
        .ring-label span {
          display: block;
          color: var(--ww-muted);
          font-size: 11px;
          font-weight: 700;
          margin-top: 2px;
        }
        .progressbar {
          height: 9px;
          border-radius: 999px;
          background: rgba(104, 115, 133, 0.16);
          overflow: hidden;
          margin: 10px 0 8px;
        }
        .progressbar > div {
          height: 100%;
          width: 0%;
          background: linear-gradient(90deg, var(--ww-teal), var(--ww-good));
          transition: width 0.35s ease;
        }
        .metrics {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 8px;
          margin: 12px 0 14px;
        }
        .metric {
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.68);
          border-radius: 8px;
          padding: 9px;
          min-width: 0;
        }
        .metric strong {
          display: block;
          font-size: 20px;
          color: var(--ww-ink);
          line-height: 1.05;
          overflow-wrap: anywhere;
        }
        .metric span {
          display: block;
          margin-top: 4px;
          color: var(--ww-muted);
          font-size: 11px;
          line-height: 1.2;
        }
        .controls {
          display: grid;
          grid-template-columns: repeat(4, minmax(120px, 1fr));
          gap: 10px;
          margin-top: 12px;
        }
        label {
          display: grid;
          gap: 5px;
          color: var(--ww-muted);
          font-size: 12px;
          font-weight: 700;
        }
        select, input {
          appearance: none;
          width: 100%;
          box-sizing: border-box;
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.92);
          border-radius: 7px;
          padding: 9px 10px;
          color: var(--ww-ink);
          font: inherit;
          min-height: 38px;
        }
        .actions {
          display: flex;
          flex-wrap: wrap;
          gap: 9px;
          margin-top: 13px;
        }
        button {
          border: 1px solid var(--ww-line);
          border-radius: 7px;
          min-height: 40px;
          padding: 0 12px;
          background: rgba(255, 255, 255, 0.82);
          color: var(--ww-ink);
          font: inherit;
          font-weight: 800;
          display: inline-flex;
          align-items: center;
          gap: 7px;
          cursor: pointer;
        }
        button.primary {
          background: var(--ww-good);
          color: white;
          border-color: rgba(15, 143, 100, 0.4);
        }
        button.stop {
          background: var(--ww-coral);
          color: white;
          border-color: rgba(200, 77, 66, 0.4);
        }
        button:disabled {
          opacity: 0.45;
          cursor: not-allowed;
        }
        .plan-list {
          display: grid;
          gap: 7px;
          max-height: 410px;
          overflow: auto;
          padding-right: 2px;
        }
        .step {
          display: grid;
          grid-template-columns: 30px minmax(0, 1fr) auto;
          gap: 9px;
          align-items: center;
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.70);
          border-radius: 8px;
          padding: 9px;
          cursor: pointer;
        }
        .step.active {
          border-color: rgba(20, 124, 140, 0.55);
          background: rgba(20, 124, 140, 0.11);
        }
        .step.done {
          opacity: 0.66;
        }
        .num {
          width: 26px;
          height: 26px;
          border-radius: 50%;
          display: grid;
          place-items: center;
          background: rgba(104, 115, 133, 0.16);
          font-weight: 850;
          font-size: 12px;
        }
        .step.active .num { background: var(--ww-teal); color: white; }
        .step-title {
          color: var(--ww-ink);
          font-weight: 850;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .step-sub {
          color: var(--ww-muted);
          font-size: 12px;
          margin-top: 2px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .attempts {
          color: var(--ww-muted);
          font-size: 12px;
          font-weight: 850;
        }
        .room {
          position: relative;
          height: 236px;
          border-radius: 8px;
          border: 1px solid var(--ww-line);
          background:
            linear-gradient(90deg, transparent 49.5%, rgba(104, 115, 133, 0.18) 50%, transparent 50.5%),
            linear-gradient(0deg, transparent 49.5%, rgba(104, 115, 133, 0.18) 50%, transparent 50.5%),
            rgba(255, 255, 255, 0.62);
          margin-top: 10px;
          overflow: hidden;
        }
        .room::before {
          content: "микрофон";
          position: absolute;
          left: 50%;
          top: 50%;
          transform: translate(-50%, -50%);
          padding: 6px 9px;
          border-radius: 999px;
          background: var(--ww-ink);
          color: white;
          font-size: 11px;
          font-weight: 850;
        }
        .point {
          position: absolute;
          transform: translate(-50%, -50%);
          border: 1px solid var(--ww-line);
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.92);
          padding: 5px 8px;
          font-size: 11px;
          font-weight: 800;
          cursor: pointer;
        }
        .point.active {
          background: var(--ww-good);
          color: white;
          border-color: rgba(15, 143, 100, 0.5);
        }
        .direction {
          margin-top: 10px;
          display: grid;
          grid-template-columns: 58px minmax(0, 1fr);
          gap: 10px;
          align-items: center;
        }
        .compass {
          position: relative;
          width: 52px;
          height: 52px;
          border-radius: 50%;
          border: 1px solid var(--ww-line);
          background: rgba(255, 255, 255, 0.75);
        }
        .needle {
          position: absolute;
          left: 50%;
          top: 50%;
          width: 3px;
          height: 21px;
          background: var(--ww-coral);
          transform-origin: 50% 100%;
          transform: translate(-50%, -100%) rotate(0deg);
          border-radius: 999px;
        }
        .direction-text {
          color: var(--ww-muted);
          font-size: 13px;
          line-height: 1.35;
        }
        .mic {
          margin-top: 12px;
          border-top: 1px solid var(--ww-line);
          padding-top: 12px;
        }
        .meter {
          height: 14px;
          border-radius: 999px;
          background: rgba(104, 115, 133, 0.16);
          overflow: hidden;
          margin: 8px 0 6px;
        }
        .meter > div {
          height: 100%;
          width: 0%;
          background: linear-gradient(90deg, #78a843, var(--ww-good), var(--ww-warn), var(--ww-coral));
          transition: width 0.08s linear;
        }
        .fineprint {
          color: var(--ww-muted);
          font-size: 11px;
          line-height: 1.35;
        }
        @media (max-width: 900px) {
          .top, .main, .hero { grid-template-columns: 1fr; }
          .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .ring { margin: 0 auto; }
        }
        @media (max-width: 520px) {
          .wrap { padding: 12px; }
          .metrics, .controls { grid-template-columns: 1fr; }
          h1 { font-size: 21px; }
          .phrase { font-size: 38px; }
        }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="top">
            <div>
              <div class="title">
                <ha-icon icon="mdi:account-voice"></ha-icon>
                <h1>Милош: запись обучающих фраз</h1>
              </div>
              <div class="subtitle" id="subtitle"></div>
            </div>
            <div class="status" id="status"><span class="dot"></span><span id="statusText">idle</span></div>
          </div>

          <div class="main">
            <div class="panel">
              <div class="hero">
                <div>
                  <div class="eyebrow" id="stepLabel"></div>
                  <div class="phrase" id="phrase"></div>
                  <div class="cue" id="cue"></div>
                </div>
                <div class="ring">
                  <svg viewBox="0 0 120 120">
                    <circle class="bg" cx="60" cy="60" r="52" fill="none" stroke-width="11"></circle>
                    <circle class="fg" id="ringFg" cx="60" cy="60" r="52" fill="none" stroke-width="11" stroke-dasharray="326.7256" stroke-dashoffset="326.7256"></circle>
                  </svg>
                  <div class="ring-label"><div><b id="ringText">0%</b><span id="ringSub">0/0</span></div></div>
                </div>
              </div>

              <div class="progressbar"><div id="progressFill"></div></div>
              <div class="metrics">
                <div class="metric"><strong id="metricObserved">0</strong><span>сработало в блоке</span></div>
                <div class="metric"><strong id="metricRemaining">0</strong><span>осталось попыток</span></div>
                <div class="metric"><strong id="metricSaved">0</strong><span>сохранено WAV</span></div>
                <div class="metric"><strong>0 / 222ч</strong><span>ложных на фоне</span></div>
              </div>

              <div class="controls">
                <label>Фраза<select id="phraseSelect"></select></label>
                <label>Говорящий<select id="speakerSelect"></select></label>
                <label>Стиль<select id="styleSelect"></select></label>
                <label>Место/шум<select id="locationSelect"></select></label>
                <label>Попыток<input id="attemptsInput" type="number" min="5" max="100" step="5"></label>
                <label>Заметка<input id="notesInput" type="text" maxlength="255" placeholder="например: гость у двери"></label>
              </div>

              <div class="actions">
                <button class="primary" id="startBtn"><ha-icon icon="mdi:record-rec"></ha-icon>Начать</button>
                <button class="stop" id="finishBtn"><ha-icon icon="mdi:stop-circle-outline"></ha-icon>Завершить</button>
                <button id="refreshBtn"><ha-icon icon="mdi:refresh"></ha-icon>Обновить</button>
                <button id="soundBtn"><ha-icon icon="mdi:volume-high"></ha-icon>Звук</button>
                <button id="micBtn"><ha-icon icon="mdi:microphone"></ha-icon>Монитор</button>
              </div>
            </div>

            <div class="panel">
              <div class="eyebrow">План записи</div>
              <div class="subtitle" id="planSubtitle"></div>
              <div class="actions">
                <button id="prevStep"><ha-icon icon="mdi:chevron-left"></ha-icon>Назад</button>
                <button id="applyStep"><ha-icon icon="mdi:tune"></ha-icon>Применить</button>
                <button id="nextStep"><ha-icon icon="mdi:chevron-right"></ha-icon>Дальше</button>
              </div>
              <div class="plan-list" id="planList"></div>
            </div>
          </div>

          <div class="main" style="margin-top:16px">
            <div class="panel">
              <div class="eyebrow">Комната и направление</div>
              <div class="room" id="room"></div>
              <div class="direction">
                <div class="compass"><div class="needle" id="needle"></div></div>
                <div class="direction-text" id="directionText"></div>
              </div>
            </div>
            <div class="panel">
              <div class="eyebrow">Микрофон и качество</div>
              <div class="mic">
                <div class="meter"><div id="micFill"></div></div>
                <div class="direction-text" id="micText"></div>
                <div class="fineprint">Этот индикатор использует микрофон браузера только для подсказки во время записи. Файлы для обучения берутся из ReSpeaker через Wyoming debug.</div>
              </div>
              <div class="metrics" style="grid-template-columns: repeat(3, minmax(0, 1fr)); margin-bottom: 0">
                <div class="metric"><strong id="metricSessions">0</strong><span>завершено сессий</span></div>
                <div class="metric"><strong id="metricRecall">0%</strong><span>попаданий в блоке</span></div>
                <div class="metric"><strong id="metricNext">1/12</strong><span>следующий шаг</span></div>
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;
    this.fillSelects();
    this.bindEvents();
    this.renderRoom();
    this.renderPlan();
  }

  fillSelects() {
    this.fillSelect("phraseSelect", LABELS.phrase);
    this.fillSelect("speakerSelect", LABELS.speaker);
    this.fillSelect("styleSelect", LABELS.style);
    this.fillSelect("locationSelect", LABELS.location);
  }

  fillSelect(id, labels) {
    const select = this.shadowRoot.getElementById(id);
    select.innerHTML = Object.entries(labels)
      .map(([value, label]) => `<option value="${this.escape(value)}">${this.escape(label)}</option>`)
      .join("");
  }

  bindEvents() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    $("phraseSelect").addEventListener("change", (event) => this.setSelect("input_select.wakeword_collection_phrase", event.target.value));
    $("speakerSelect").addEventListener("change", (event) => this.setSelect("input_select.wakeword_collection_speaker", event.target.value));
    $("styleSelect").addEventListener("change", (event) => this.setSelect("input_select.wakeword_collection_style", event.target.value));
    $("locationSelect").addEventListener("change", (event) => this.setSelect("input_select.wakeword_collection_location", event.target.value));
    $("attemptsInput").addEventListener("change", (event) => this.setNumber("input_number.wakeword_collection_expected_attempts", event.target.value));
    $("notesInput").addEventListener("change", (event) => this.setText("input_text.wakeword_collection_notes", event.target.value));
    $("startBtn").addEventListener("click", () => this.startSession());
    $("finishBtn").addEventListener("click", () => this.finishSession());
    $("refreshBtn").addEventListener("click", () => this.refreshSession());
    $("soundBtn").addEventListener("click", () => this.setSoundEnabled(!this.soundEnabled()));
    $("micBtn").addEventListener("click", () => this.toggleMicMonitor());
    $("prevStep").addEventListener("click", () => this.selectPlanStep(this.currentPlanIndex() - 1));
    $("nextStep").addEventListener("click", () => this.selectPlanStep(this.currentPlanIndex() + 1));
    $("applyStep").addEventListener("click", () => this.applyStep(WAKEWORD_PLAN[this.currentPlanIndex()]));
  }

  currentPlanIndex() {
    return Math.max(0, Math.min(WAKEWORD_PLAN.length - 1, Number(this.value("input_number.wakeword_collection_plan_step", 1)) - 1));
  }

  renderPlan() {
    const list = this.shadowRoot.getElementById("planList");
    list.innerHTML = WAKEWORD_PLAN.map((step, index) => `
      <div class="step" data-step="${index}">
        <div class="num">${index + 1}</div>
        <div>
          <div class="step-title">${this.escape(step.name)}</div>
          <div class="step-sub">${this.escape(LABELS.phrase[step.phrase])} · ${this.escape(LABELS.speaker[step.speaker])} · ${this.escape(LABELS.location[step.location])}</div>
        </div>
        <div class="attempts">${step.attempts}x</div>
      </div>
    `).join("");
    list.querySelectorAll(".step").forEach((node) => {
      node.addEventListener("click", () => this.selectPlanStep(Number(node.dataset.step)));
    });
  }

  renderRoom() {
    const room = this.shadowRoot.getElementById("room");
    room.innerHTML = ROOM_POINTS.map((point) => `
      <button class="point" data-location="${this.escape(point.id)}" style="left:${point.x}%;top:${point.y}%">${this.escape(point.label)}</button>
    `).join("");
    room.querySelectorAll(".point").forEach((node) => {
      node.addEventListener("click", () => this.setSelect("input_select.wakeword_collection_location", node.dataset.location));
    });
  }

  update() {
    if (!this.shadowRoot || !this._hass) return;
    const active = this.value("sensor.wakeword_positive_session") === "active";
    const observed = Number(this.attr("sensor.wakeword_positive_session", "wake_files_since_start", 0));
    const expected = Number(this.attr("sensor.wakeword_positive_session", "expected_attempts", this.value("input_number.wakeword_collection_expected_attempts", 30))) || 30;
    const progress = expected > 0 ? Math.min(1, observed / expected) : 0;
    const planIndex = this.currentPlanIndex();
    const step = WAKEWORD_PLAN[planIndex];
    const phrase = this.value("input_select.wakeword_collection_phrase", step.phrase);
    const speaker = this.value("input_select.wakeword_collection_speaker", step.speaker);
    const style = this.value("input_select.wakeword_collection_style", step.style);
    const location = this.value("input_select.wakeword_collection_location", step.location);
    const totalSaved = Number(this.attr("sensor.wakeword_positive_session", "real_positive_files_total", 0));
    const sessions = Number(this.attr("sensor.wakeword_positive_session", "session_summaries_total", 0));
    const recall = expected > 0 ? Math.round((observed / expected) * 100) : 0;
    const totalPlan = WAKEWORD_PLAN.reduce((sum, item) => sum + item.attempts, 0);

    this.shadowRoot.getElementById("subtitle").textContent =
      `План: ${WAKEWORD_PLAN.length} блоков, ${totalPlan} попыток. Текущий блок: ${LABELS.speaker[speaker] || speaker}, ${LABELS.style[style] || style}, ${LABELS.location[location] || location}.`;
    this.shadowRoot.getElementById("status").classList.toggle("active", active);
    this.shadowRoot.getElementById("statusText").textContent = active ? "идет запись" : "готово";
    this.shadowRoot.getElementById("stepLabel").textContent = `Шаг ${planIndex + 1} из ${WAKEWORD_PLAN.length} · ${step.name}`;
    this.shadowRoot.getElementById("phrase").textContent = LABELS.phrase[phrase] || phrase;
    this.shadowRoot.getElementById("cue").textContent = step.cue;
    this.shadowRoot.getElementById("ringText").textContent = `${Math.min(100, Math.round(progress * 100))}%`;
    this.shadowRoot.getElementById("ringSub").textContent = `${observed}/${expected}`;
    this.shadowRoot.getElementById("ringFg").style.strokeDashoffset = String(326.7256 * (1 - progress));
    this.shadowRoot.getElementById("progressFill").style.width = `${Math.min(100, Math.round(progress * 100))}%`;
    this.shadowRoot.getElementById("metricObserved").textContent = String(observed);
    this.shadowRoot.getElementById("metricRemaining").textContent = String(Math.max(0, expected - observed));
    this.shadowRoot.getElementById("metricSaved").textContent = String(totalSaved);
    this.shadowRoot.getElementById("metricSessions").textContent = String(sessions);
    this.shadowRoot.getElementById("metricRecall").textContent = `${recall}%`;
    this.shadowRoot.getElementById("metricNext").textContent = `${planIndex + 1}/${WAKEWORD_PLAN.length}`;
    this.shadowRoot.getElementById("planSubtitle").textContent =
      `Сделано блоков: ${this.value("counter.wakeword_collection_blocks_done", 0)}. После завершения следующий шаг выбирается автоматически.`;

    this.setControlValue("phraseSelect", phrase);
    this.setControlValue("speakerSelect", speaker);
    this.setControlValue("styleSelect", style);
    this.setControlValue("locationSelect", location);
    this.setControlValue("attemptsInput", expected);
    if (this.shadowRoot.activeElement?.id !== "notesInput") {
      this.setControlValue("notesInput", this.value("input_text.wakeword_collection_notes", ""));
    }

    this.shadowRoot.getElementById("startBtn").disabled = active;
    this.shadowRoot.getElementById("finishBtn").disabled = !active;
    this.shadowRoot.getElementById("soundBtn").innerHTML =
      `<ha-icon icon="${this.soundEnabled() ? "mdi:volume-high" : "mdi:volume-off"}"></ha-icon>${this.soundEnabled() ? "Звук вкл" : "Звук выкл"}`;
    this.shadowRoot.getElementById("micBtn").innerHTML =
      `<ha-icon icon="${this.micStream ? "mdi:microphone" : "mdi:microphone-outline"}"></ha-icon>${this.micStream ? "Остановить" : "Монитор"}`;

    this.shadowRoot.querySelectorAll(".step").forEach((node) => {
      const index = Number(node.dataset.step);
      node.classList.toggle("active", index === planIndex);
      node.classList.toggle("done", index < planIndex);
    });
    this.shadowRoot.querySelectorAll(".point").forEach((node) => {
      node.classList.toggle("active", node.dataset.location === location);
    });
    this.updateDirection(location);
    this.updateMicOnly();
  }

  updateDirection(location) {
    const entityId = this.config?.direction_entity || "sensor.wakeword_mic_direction";
    const raw = this.value(entityId, "");
    const numeric = raw === "" ? NaN : Number(raw);
    const point = ROOM_POINTS.find((item) => item.id === location);
    const needle = this.shadowRoot.getElementById("needle");
    const text = this.shadowRoot.getElementById("directionText");
    if (Number.isFinite(numeric)) {
      needle.style.transform = `translate(-50%, -100%) rotate(${numeric}deg)`;
      text.textContent = `Направление от микрофонного массива: ${Math.round(numeric)} градусов. Выбранная позиция: ${LABELS.location[location] || location}.`;
    } else {
      const angle = point ? Math.atan2(point.y - 50, point.x - 50) * 180 / Math.PI + 90 : 0;
      needle.style.transform = `translate(-50%, -100%) rotate(${angle}deg)`;
      text.textContent = `Live direction sensor пока не подключен. Стрелка показывает выбранную позицию записи: ${LABELS.location[location] || location}.`;
    }
  }

  updateMicOnly() {
    if (!this.shadowRoot) return;
    const level = Math.max(0, Math.min(1, this.micLevel || 0));
    const db = Number.isFinite(this.micDb) ? this.micDb : -90;
    const micFill = this.shadowRoot.getElementById("micFill");
    const micText = this.shadowRoot.getElementById("micText");
    if (!micFill || !micText) return;
    micFill.style.width = `${Math.round(level * 100)}%`;
    if (this.micStream) {
      const hint = db > -18 ? "громко" : db > -34 ? "хороший уровень" : db > -52 ? "тихо" : "почти тишина";
      micText.textContent = `Браузерный микрофон: ${Math.round(db)} dBFS, ${hint}.`;
    } else if (this.micError) {
      micText.textContent = `Браузерный микрофон недоступен: ${this.micError}`;
    } else {
      micText.textContent = "Монитор выключен. Запись для обучения все равно идет через ReSpeaker/Wyoming debug.";
    }
  }

  setControlValue(id, value) {
    const element = this.shadowRoot.getElementById(id);
    if (element && String(element.value) !== String(value)) element.value = value;
  }

  escape(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}

if (!customElements.get("wakeword-collection-card")) {
  customElements.define("wakeword-collection-card", WakewordCollectionCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "wakeword-collection-card")) {
  window.customCards.push({
    type: "wakeword-collection-card",
    name: "Wakeword Collection Card",
    preview: false,
    description: "Guided wake word positive dataset collection for Home Assistant.",
  });
}
