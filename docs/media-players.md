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

## «Гостиная (Chromecast)» and the Google TV remote

Checked on 2026-09-27 with MA 2.10.4 and the output protocol set to "Native" (Sendspin off).
Remote presses were sent through the Android TV Remote integration (`remote.send_command` on
`remote.televizor`), the same channel the phone remote app uses.

How MA casts here: it launches its own Cast receiver app "Music Assistant" (app id `C35B0678`,
<https://cast.music-assistant.io/>, source in `music-assistant/cast-receiver`), not Google's
default media receiver. That is the player's advanced setting "Use Music Assistant Cast App",
which is on by default. Keep it on: the MA app forwards next/previous to MA, the default receiver
would not. The audio is encoded live and sent as a Cast `LIVE` stream with no duration, and MA's
stream server does not support HTTP range requests.

"Flow mode" (one continuous stream for the whole queue) is on for Cast players by default. On
this queue crossfade forces it anyway, because Cast players do not report gapless support.
Turning both flow mode and crossfade off was tested: the remote behaved exactly the same, so both
were set back.

What the remote does:

| Key | Result |
|---|---|
| D-pad centre | Pause / play. Works. |
| D-pad left / right | Nothing. The receiver never gets a seek request for a live stream. |
| Back | Nothing: the player screen stays and the music keeps playing. |
| Home | Goes to the Google TV home screen; the music keeps playing in the background. |
| Media previous / next (phone remote app, remotes with media keys) | Work while the player screen or the home screen is in front. Next goes to the next track. Previous goes to the previous track within the first 5 s of a track, otherwise it restarts the current one. Each takes 2–4 s. While another app (e.g. YouTube) is in front the keys do not reach the cast, and media next twice froze playback (still shown as playing) until pause/play from MA. |

The Google TV remote has no previous-track key, so "back" on it means the Back key.

Seeking: seek from MA or from `media_player.gostinaia`, where MA restarts the stream at the new
position. Do not seek through the Cast receiver itself, e.g. the Google Home app, a phone's cast
notification or HA's own Cast entity `media_player.gostinaia_2`. The receiver advertises seek and
handles a jump within what it has already buffered. A longer jump makes it request the stream
again, MA starts that stream over, the receiver reports media error 104 and skips to the next
track. Proper remote seek needs MA's receiver app to forward seek to MA, the way it already
forwards next/previous. That is an upstream change; no player setting fixes it.

In flow mode, resuming after a long pause (11 h) once jumped back to the first track of that flow
stream, because the receiver requested the stream again.

### Getting the player screen back after Home

- Google TV keeps the cast playing in the background. Google's notes for Chromecast built-in
  1.47 and later describe a notification with "Open" and "Stop". To reach it, hold Home, or
  select the settings icon at the top right of the home screen, go to Notifications and choose
  Open. Not yet checked on this TV's screen.
- A way back that was checked: in MA (or HA, `media_player.gostinaia`) press Stop, wait 15 s,
  then press Play. MA releases the Cast app 10 s after a stop, and the next Play launches it again
  full screen. That launch also switches the TV on over HDMI-CEC. Play or next alone, without the
  Stop and the wait, does not bring the screen back.

### Alternative: a Sendspin player app on the TV

A native Android TV app with an Android media session gets Google TV's "Now playing" controls and
the media keys. There are two candidates; neither is installed here:

- SendspinDroid: Google Play `com.sendspindroid`, closed beta. Play/pause/next/previous, optional
  start at boot.
- MassDroid TV: `sfortis/massdroid_native`, GitHub releases only. Seek and next/previous, keeps
  playing after Home.

Either app adds a separate Sendspin player in MA, and the app has to stay running.
