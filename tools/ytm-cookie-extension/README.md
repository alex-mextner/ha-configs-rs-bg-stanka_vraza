# YT Music → Music Assistant (Chrome extension)

One click copies the `music.youtube.com` cookie that Music Assistant's YouTube Music provider needs
(no DevTools). Then `ssh -t root@home ytm-cookie` (paste, Enter) creates or updates the provider
through MA's own setup flow (Premium is checked there).

Install once: `chrome://extensions` → Developer mode → Load unpacked → this folder. Pin the icon.
When YouTube Music in MA stops working (the cookie rotated), repeat: click → run the command.

Tip: use a separate Chrome profile only for YouTube Music, signed in once and otherwise untouched;
Google rotates the cookie of an account that is also used for everyday browsing.
