class NativeChatGPTPanel extends HTMLElement {
  set hass(value) {
    this._hass = value;
    if (!this._starting) {
      this._starting = true;
      this.start();
    }
  }
  async authorize() {
    const {session} = await this._hass.callWS({type: "ha-ingress/session"});
    await this._hass.callApi("POST", "chatgpt_native/session", {session});
  }
  async start() {
    this.innerHTML = '<p>Подключение к отдельной сессии ChatGPT…</p>';
    try {
      await this.authorize();
      this.innerHTML = '<iframe title="Native ChatGPT" style="border:0;width:100%;height:100%;position:absolute;inset:0" allow="clipboard-read; clipboard-write"></iframe>';
      this.querySelector('iframe').src = '/api/chatgpt_native/vnc.html?autoconnect=true&resize=scale&path=api/chatgpt_native/websockify';
      this._timer = setInterval(() => this.authorize().catch(() => {
        clearInterval(this._timer);
        this.innerHTML = '<p>Сессия HA истекла. Войдите снова.</p>';
      }), 120000);
    } catch (_) {
      this.innerHTML = '<p>Доступ разрешён только действующим администраторам HA.</p>';
    }
  }
  disconnectedCallback() { clearInterval(this._timer); }
}
customElements.define('chatgpt-native-panel', NativeChatGPTPanel);
