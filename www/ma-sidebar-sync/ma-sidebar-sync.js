/* Music Assistant ⇄ Home Assistant sidebar sync: on a desktop-width screen only one of the two
 * sidebars stays expanded. Opening Music Assistant expands its sidebar and collapses Home Assistant's;
 * expanding either one by hand collapses the other. See docs/ma-sidebar-sync.md.
 *
 * Loaded into Music Assistant's index.html by the `music_assistant` ingress rewrite in
 * configuration.yaml. The ingress iframe shares Home Assistant's origin, so window.parent is the Home
 * Assistant shell. Nothing used here is a public API of either app; when an update renames something,
 * the sync quietly stops and both apps keep working.
 */
(() => {
  const TAG = '[ma-sidebar-sync]';

  let main = null;
  try {
    main = window.parent === window ? null : window.parent.document
      .querySelector('home-assistant')?.shadowRoot?.querySelector('home-assistant-main');
  } catch (err) {
    // framed by a page of another origin
  }
  if (!main) {
    console.debug(TAG, 'not inside the Home Assistant shell, idle');
    return;
  }

  // Home Assistant: docked sidebar that is not an overlay drawer (narrow, always hidden, kiosk).
  const haExpanded = () => main.hasAttribute('expanded') && !main.hasAttribute('modal');
  // Music Assistant: the desktop sidebar; the mobile sheet has no expanded/collapsed state.
  const maExpanded = () => !!document.querySelector('[data-slot="sidebar"][data-state="expanded"]');

  // The event Home Assistant's own menu button fires; {open: false} undocks the sidebar.
  const collapseHa = () => {
    if (!haExpanded()) return;
    main.dispatchEvent(new window.parent.CustomEvent('hass-toggle-menu', {
      detail: { open: false }, bubbles: true, composed: true,
    }));
  };
  // Music Assistant's sidebar toggles on Ctrl+B and has no other handle from outside.
  const collapseMa = () => {
    if (!maExpanded()) return;
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true }));
  };

  // Opening Music Assistant: its sidebar reads this cookie when it mounts, so it starts expanded.
  document.cookie = 'sidebar_state=true; path=/; max-age=604800';
  collapseHa();

  // Act on the transition to expanded only: collapsing one side then never feeds back into the other,
  // and an attribute write landing in the same tick as the user's click cannot undo that click.
  let haWas = haExpanded();
  let maWas = maExpanded();
  const observer = new MutationObserver(() => {
    if (!main.isConnected || !window.frameElement) {
      observer.disconnect();
      return;
    }
    const ha = haExpanded();
    const ma = maExpanded();
    if (ha && !haWas) collapseMa();
    else if (ma && !maWas) collapseHa();
    haWas = ha;
    maWas = ma;
  });
  observer.observe(main, { attributes: true, attributeFilter: ['expanded', 'modal'] });
  observer.observe(document.documentElement, {
    attributes: true, attributeFilter: ['data-state'], childList: true, subtree: true,
  });
  window.addEventListener('pagehide', () => observer.disconnect());
})();
