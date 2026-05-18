class HaPanelCode extends HTMLElement {
  connectedCallback() {
    this.innerHTML = '<iframe src="http://homeassistant-code-server-1:8080" style="width:100%;height:100%;border:none;"></iframe>';
  }
}
customElements.define("ha-panel-code", HaPanelCode);
