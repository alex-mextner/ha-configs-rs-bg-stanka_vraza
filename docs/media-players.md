# Media players: which is which

The living-room TV is a Samsung UE48J5500 with a Chromecast HD dongle plugged into it. Together they
show up as several players in Home Assistant and Music Assistant (MA). State as of 2026-09-26.

| Name | Entity | What it is | Use it for |
|---|---|---|---|
| «Гостиная (Chromecast)» | `media_player.gostinaia` | MA's player for the Chromecast HD dongle (192.168.0.24 as of 2026-09-26, DHCP) | Music. Alice sees it as «Телевизор» (`packages/alice_music.yaml`), so keep the entity_id |
| «Chromecast — пульт» | `media_player.televizor` | Android TV Remote for the same dongle | Power, buttons, apps only. It cannot play music: `play_media` with media type `music` fails with "Invalid media type" |
| «Гостиная» (HA Cast) | `media_player.gostinaia_2` | HA's own Cast integration, straight to the dongle, bypassing MA | Casting without MA |
| «[TV] UE48J5500» (hidden) | `media_player.tv_ue48j5500_2` | The Samsung's own DLNA renderer, as an MA player | Only when the Chromecast is off or unplugged; see below |
| «UE48J5500 (UE48J5500)» | `media_player.ue48j5500_ue48j5500` | Samsung TV integration | The TV's power, volume and source |

`media_player.tv_ue48j5500` (HA's own DLNA integration for the same renderer) is disabled; do not
confuse it with `media_player.tv_ue48j5500_2`.

## Why «[TV] UE48J5500» is hidden

It was hidden in MA ("Hide in UI") and in HA (entity hidden by user, not disabled) on 2026-09-26:

- it takes over the TV screen with its full-screen player;
- it refused MA's stream with UPnP error 701 "Transition not available" at 14:57 on 2026-09-26
  (12:57 UTC in MA's log), probably while the TV was on an HDMI input;
- it plays through the same TV speakers as the Chromecast, so it is a confusing duplicate.

Its only use is when the Chromecast is off or unplugged. To bring it back, untick "Hide in UI" on
the player in MA (Settings > Players > [TV] UE48J5500) and unhide `media_player.tv_ue48j5500_2` in
HA (Settings > Entities > the entity > Visible).

Logs: [aisis#23](https://github.com/alex-mextner/aisis/issues/23).
