class NativeChatGPTPanel extends HTMLElement {
  get desktopMode() { return false; }
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
    this.innerHTML = this.desktopMode ? '<p>Подключение к Ubuntu Desktop…</p>' : '<p>Подключение к отдельной сессии ChatGPT…</p>';
    try {
      await this.authorize();
      const notice = this.desktopMode ? '<div style="height:64px;box-sizing:border-box;padding:8px;background:var(--card-background-color);font:14px sans-serif">Ubuntu Desktop и ChatGPT — общая сессия. Переключение окон видно в обеих панелях.</div>' : '';
      const top = this.desktopMode ? '64px' : '0';
      this.innerHTML = notice + '<iframe title="' + (this.desktopMode ? 'Ubuntu Desktop' : 'Native ChatGPT') + '" style="border:0;width:100%;height:calc(100% - ' + top + ');position:absolute;inset:' + top + ' 0 0 0" allow="clipboard-read; clipboard-write"></iframe>';
      this.querySelector('iframe').src = '/api/chatgpt_native/vnc.html?autoconnect=true&resize=scale&path=/api/chatgpt_native/websockify';
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
class NativeUbuntuDesktopPanel extends NativeChatGPTPanel {
  get desktopMode() { return true; }
}
customElements.define('ubuntu-desktop-panel', NativeUbuntuDesktopPanel);
