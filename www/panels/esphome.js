class HaPanelEsphome extends HTMLElement {
  connectedCallback() {
    this.innerHTML = '<iframe src="http://homeassistant-esphome-1:6052" style="width:100%;height:100%;border:none;"></iframe>';
  }
}
customElements.define("ha-panel-esphome", HaPanelEsphome);
