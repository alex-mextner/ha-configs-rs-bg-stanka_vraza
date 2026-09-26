# YT Music → Music Assistant (Chrome extension)

One click copies the `music.youtube.com` cookie that Music Assistant's YouTube Music provider needs
(no DevTools). Then `ssh -t root@home ytm-cookie` (paste, Enter) creates or updates the provider
through MA's own setup flow (Premium is checked there).

Install once: `chrome://extensions` → Developer mode → Load unpacked → this folder. Pin the icon.
When YouTube Music in MA stops working (the cookie rotated), repeat: click → run the command.

Tip: use a separate Chrome profile only for YouTube Music, signed in once and otherwise untouched;
Google rotates the cookie of an account that is also used for everyday browsing.

## Several people (aisis#17)

Each person (or guest) can have their own YouTube Music account in MA; their likes then land in
their own account. Click the extension in the browser profile where **that person** is signed in,
then:

    ssh -t root@home ytm-cookie --person lena            # Lena's account (HA person / username)
    ssh -t root@home ytm-cookie --guest "Вася" --days 2  # a guest, removed after 2 days (1-7)
    ssh -t root@home ytm-cookie                          # the household default, as before
    ssh root@home ytm-cookie --person lena --dry-run     # only check that MA would take it

The same for Yandex Music: `ssh -t root@home yandex-music-token --person lena --device` shows an
address and a code; the person enters it while signed in to their own Yandex account.
`ssh root@home music-accounts list` shows who has which account.
