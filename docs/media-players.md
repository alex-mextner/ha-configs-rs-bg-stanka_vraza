# Media players: which is which

The living-room TV is a Samsung UE48J5500 with a Chromecast HD dongle plugged into it. Together they
show up as several players in Home Assistant and Music Assistant (MA). State as of 2026-09-26.

| Name | Entity | What it is | Use it for |
|---|---|---|---|
| «Гостиная (Chromecast)» | `media_player.gostinaia` | MA's player for the Chromecast HD dongle (192.168.0.24 as of 2026-09-26, DHCP) | Music. Alice sees it as «Телевизор» (`packages/alice_music.yaml`), so keep the entity_id |
| «Chromecast — пульт» | `media_player.televizor` | Android TV Remote for the same dongle | Power, buttons, apps only. It cannot play music: `play_media` with media type `music` fails with "Invalid media type" |
| «Гостиная» (HA Cast) | `media_player.gostinaia_2` | HA's own Cast integration, straight to the dongle, bypassing MA | Casting without MA |
| «[TV] UE48J5500» (disabled) | none (was `media_player.tv_ue48j5500_2`) | The Samsung's own DLNA renderer, as an MA player | Nothing; disabled in MA, see below |
| «UE48J5500 (UE48J5500)» | `media_player.ue48j5500_ue48j5500` | Samsung TV integration | The TV's power, volume and source |

`media_player.tv_ue48j5500` (HA's own DLNA integration for the same renderer) is disabled as well; it
is a different entity from the removed `media_player.tv_ue48j5500_2`.

## Why «[TV] UE48J5500» is disabled

On 2026-09-26 it was first hidden in MA and HA, and later the same day disabled in MA for good,
because the Samsung's DLNA player is not wanted at all:

- it takes over the TV screen with its full-screen player;
- it refused MA's stream with UPnP error 701 "Transition not available" at 14:57 on 2026-09-26
  (12:57 UTC in MA's log), probably while the TV was on an HDMI input;
- it plays through the same TV speakers as the Chromecast, so it is a confusing duplicate.

What was done:

- MA player `up42da6e87` («[TV] UE48J5500», a universal player) was set to `enabled: false` in its
  MA player config. MA cascaded that to the linked DLNA protocol player
  `uuid:c04cf2e8-5132-462a-bd1a-1e5cc580ff47`, and a disabled parent stops MA from wrapping the
  renderer in a new universal player when DLNA discovery finds it again.
- The DLNA provider itself stays enabled: it also carries Kodi's renderer («Kodi (home)»,
  `uuid:ca958b68-8b38-f503-168e-7a2086668c64`).
- In HA the orphaned MA device and its entities (`media_player.tv_ue48j5500_2`,
  `button.tv_ue48j5500_favorite_current_song`) were removed from the registry, after reloading
  the Music Assistant integration so that it no longer knew the player. Removing the device while
  the integration still lists the player makes HA delete the player config in MA, and MA would
  then rediscover the TV as a new, enabled player. Deleting only the HA entity would not stick
  either: the integration recreates it as long as the player is enabled in MA.
- It was never in the Yandex Smart Home (Alice) include list, and it is no longer exposed to Assist.

To re-enable it: MA > Settings > Players > [TV] UE48J5500 > Enable. MA brings back the DLNA
protocol player with it, and the MA integration creates a new HA entity (possibly with a new
entity_id), which then needs to be exposed to Assist again if wanted. The player keeps MA's
"Hide in UI" setting, so untick that too if it should show up in MA.

Logs: [aisis#23](https://github.com/alex-mextner/aisis/issues/23).
