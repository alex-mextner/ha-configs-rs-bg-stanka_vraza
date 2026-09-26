# Music Assistant ⇄ Home Assistant sidebar sync

The Music Assistant panel (`ingress: music_assistant` in `configuration.yaml`) shows two sidebars side
by side: Home Assistant's and Music Assistant's own. On a desktop-width screen only one of them stays
expanded:

- opening Music Assistant expands its sidebar and collapses Home Assistant's to the icon rail;
- expanding Home Assistant's sidebar by hand collapses Music Assistant's;
- expanding Music Assistant's sidebar by hand collapses Home Assistant's.

Leaving Music Assistant does not restore Home Assistant's sidebar: Home Assistant keeps whatever state
it was last put in, as it always does. Narrow screens are left alone, since both sidebars are overlay
drawers there.

## How

No patches to Home Assistant, Music Assistant or `hass_ingress`. A second `rewrite` rule of the
`music_assistant` ingress panel adds `<script src="/local/ma-sidebar-sync/ma-sidebar-sync.js">` to
Music Assistant's `index.html` (the first rule injects the auto-login snippet). The panel's iframe is
served from Home Assistant's own origin (`/api/ingress/<token>/`), so the script reaches the Home
Assistant shell through `window.parent`. Home Assistant does not cache custom panels, so the iframe,
and the script with it, starts over every time the panel is opened.

| Step | Trigger | Action |
|---|---|---|
| 1 | the script loads, before Music Assistant starts | cookie `sidebar_state=true` (Music Assistant opens expanded); collapse Home Assistant |
| 2 | Home Assistant's sidebar goes from collapsed to expanded | collapse Music Assistant |
| 3 | Music Assistant's sidebar goes from collapsed (or absent) to expanded | collapse Home Assistant |

Steps 2 and 3 fire on the transition only, so collapsing one side never feeds back into the other.
Nothing happens while Home Assistant's sidebar is modal (narrow window, "Always hide the sidebar",
kiosk mode) or while Music Assistant uses its mobile layout.

## What it relies on

None of this is a public API of either app. If an update renames something, the sync quietly stops
and both apps keep working; re-check these against the new sources. The script logs one
`console.debug` line when it cannot find the Home Assistant shell.

- Home Assistant (frontend `src/layouts/home-assistant-main.ts`): `<home-assistant-main>` in the shadow
  root of `<home-assistant>` reflects the attributes `expanded` (sidebar docked) and `modal`; the
  `hass-toggle-menu` event with `{open: false}` undocks the sidebar, as Home Assistant's own menu button
  does.
- `hass_ingress` registers the panel with `embed_iframe=False`, so Music Assistant's frame sits directly
  in the Home Assistant page and `window.parent` is the shell (with the extra custom-panel iframe it
  would be one level deeper).
- Music Assistant (frontend `src/components/ui/sidebar/`): the desktop sidebar is
  `[data-slot="sidebar"][data-state="expanded"|"collapsed"]`; it starts open unless the cookie
  `sidebar_state=false` is set; Ctrl+B on `window` toggles it.

Checked against Home Assistant 2026.9.3 (frontend 20260826.7) and Music Assistant 2.10.4 (frontend
2.17.297).

## Upstream

Home Assistant's add-on panel (`ha-panel-app`) already speaks a postMessage protocol with its iframe,
and Music Assistant uses it, but only as a Supervisor add-on under `/hassio_ingress/`, and to take Home
Assistant into kiosk mode rather than to share the screen. Doing this upstream would take changes to
Home Assistant, Music Assistant and `hass_ingress` alike, so it lives here instead.
