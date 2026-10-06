// Render both registered panels without a browser or real HA credentials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const registry = new Map();
class Element {
  constructor() { this.frame = {}; }
  querySelector() { return this.frame; }
}
const sandbox = {HTMLElement: Element, customElements: {define: (n,c) => registry.set(n,c)}, setInterval: () => 1, clearInterval: () => {}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('custom_components/chatgpt_native/panel.js', 'utf8'), sandbox);
(async () => {
  for (const name of ['chatgpt-native-panel', 'ubuntu-desktop-panel']) {
    assert.ok(registry.has(name), name + ' registered');
    const panel = new (registry.get(name))();
    panel._hass = {callWS: async () => ({session: 'test-only'}), callApi: async (method, url) => {assert.equal(method, 'POST'); assert.equal(url, 'chatgpt_native/session');}};
    await panel.start();
    assert.equal(panel.frame.src, '/api/chatgpt_native/vnc.html?autoconnect=true&resize=scale&path=/api/chatgpt_native/websockify');
    if (name === 'ubuntu-desktop-panel') assert.match(panel.innerHTML, /общая сессия/i);
  }
  console.log('PASS both panels retain the same authenticated API and disclose shared session');
})();
