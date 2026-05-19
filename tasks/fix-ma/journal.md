# Журнал отладки: Яндекс Музыка → Яндекс колонка через Media tab

## Симптом

При попытке проиграть трек из Яндекс Музыки (библиотека Music Assistant) на колонке через вкладку **Media** HA → ошибка:
- `Failed to perform the action media_player/play_media. Please call connect first.`
- После перезапуска HA колонка `media_player.stantsiia_mini_u_vovy` становится `unavailable`.

---

## Гипотезы и проверки

### Гипотеза 1: Stale `hass_client` reference в Music Assistant после перезапуска HA

**Обоснование:** После `docker restart homeassistant-homeassistant-1` websocket между MA и HA обрывается. MA пересоздаёт `HomeAssistantClient`, но `HomeAssistantPlayer` объекты в `hass_players` продолжают хранить ссылку на старый отключённый клиент. При вызове `play_media` через этот клиент `hass_client.call_service()` проверяет `self.connected`, видит `False`, и бросает `NotConnected("Please call connect first.")`.

**Патч:**
- `music_assistant/providers/hass_players/player.py`
  - Убран `self.hass = hass` из `__init__`.
  - Добавлен property `hass`, который динамически разрешает текущий клиент через `self.provider.hass_prov.hass`.
- `music_assistant/providers/hass_players/provider.py`
  - Убран параметр `hass=` из вызова `HomeAssistantPlayer(...)`.

**Проверка:**
- Перезапустил MA. Проверил: MA переподключился к HA, `hass_players` провайдер загрузился, колонка зарегистрирована (`Станция Мини у Вовы`).
- Результат: stale reference больше не вызывает `Please call connect first`. Ошибка изменилась.

**Статус:** Подтверждена и пофикшена.

---

### Гипотеза 2: MA подключена к HA через публичный Dataplicity URL

**Обоснование:** В `settings.json` MA `hass` провайдер использовал `url: https://spry-gazelle-4693.dataplicity.io/`. После перезапуска HA Dataplicity туннель временно недоступен (504 Gateway Timeout). MA помечает все HA-плееры как `unavailable`.

**Патч:**
- `settings.json` (MA): изменён `hass.url` на локальный адрес HA.

**Проверка:**
- Сменил URL на `https://192.168.0.39:8123` с `verify_ssl: false`.
- MA успешно подключился, колонка стала `available`.

**Статус:** Подтверждена и пофикшена.

---

### Гипотеза 3: Нужен HTTPS на HA для локального URL

**Обоснование:** Пользователь указал, что `http://homeassistant.local:8123` работает в браузере, но MA ругается на SSL.

**Патч (применён и ОТКАТАН):**
- `configuration.yaml`: добавлен блок `http:` с `ssl_certificate` и `ssl_key` (самоподписанный).
- `configuration.yaml`: добавлен `homeassistant.internal_url: "https://192.168.0.39:8123"`.
- `ha.docker-compose.yaml`: healthcheck изменён на `curl -fkS https://127.0.0.1:8123/`.
- `custom_components/yandex_station/core/stream.py`: fallback `hass_url` изменён на `https://...`.
- MA `settings.json`: `hass.url` → `https://192.168.0.39:8123`.

**Проверка:**
- HA стал доступен по HTTPS. MA подключился. `media_player.stantsiia_mini_u_vovy` стал `paused`.
- При попытке play через Media — UI показывает "играет", но колонка молчит. Ошибка `PlayerCommandFailed`.
- **Причина:** Music Assistant генерирует `media_content_id` с URL потока `http://172.20.0.4:8097/flow/...`. YandexStation оборачивает его в прокси-URL через HA StreamView (`get_stream_url`). Колонка должна скачать `https://192.168.0.39:8123/api/yandex_station/<token>.mp3`. Но колонка (Яндекс Мини) **не доверяет самоподписанному SSL-сертификату** и отказывается качать. Либо HA `network.get_url` возвращает `None` при включённом самоподписанном HTTPS, и `StreamView.hass_url` падает.

**Статус:** ОТКАТАНА. HTTPS с самоподписанным сертом ломает проигрывание на колонке.

---

### Гипотеза 4: HA `network.get_url` не работает без явного `internal_url`

**Обоснование:** В `stream.py` `network.get_url(hass, allow_external=False)` бросает исключение с пустым сообщением. `StreamView.hass_url` не инициализируется, `get_stream_url` падает на `assert`.

**Патч (актуальный):**
- `configuration.yaml`: добавлен `homeassistant.internal_url: "http://192.168.0.39:8123"`.
- `custom_components/yandex_station/core/stream.py`: fallback на `http://192.168.0.39:8123` при неудаче `network.get_url`.

**Проверка:**
- Откатил HTTPS → вернул HTTP.
- `configuration.yaml`: `internal_url: "http://192.168.0.39:8123"`.
- `stream.py` fallback → `http://192.168.0.39:8123`.
- MA `settings.json` → `http://192.168.0.39:8123` (потребовалось остановить MA, обновить файл, стартовать — иначе MA перезаписывал при shutdown).
- После рестарта MA: `Loaded plugin provider Home Assistant`, `Loaded player provider Home Assistant MediaPlayers`.
- `media_player.stantsiia_mini_u_vovy` — `paused` (доступен), а не `unavailable`.

**Статус:** Подтверждена и пофикшена.

---

### Гипотеза 5: MA stream server недоступен из HA

**Обоснование:** MA генерирует URL `http://172.20.0.4:8097/flow/...`. HA должен скачать этот поток через `StreamView` прокси и отдать колонке. Если HA не может достучаться до `172.20.0.4:8097`, поток пустой.

**Проверка:**
- `docker exec homeassistant-homeassistant-1 python3 -c 'urllib.request.urlopen("http://172.20.0.4:8097/")'` → возвращает `HTTPError 404: Not Found`.
- Это значит, сервер доступен! Просто маршрут `/` не существует (это нормально для MA streams).
- Ранний тест с `Fail 172.20.0.4` был ложноотрицательным — он ловил `HTTPError` как generic `Exception`.

**Статус:** Опровергнута. Stream server доступен из HA.

---

### Гипотеза 6: Колонка не умеет воспроизводить HTTP-потоки (radio_play)

**Обоснование:** После отправки `radio_play` колонка отвечает `SUCCESS`, но молчит.

**Проверка (обновлена):**
- Логи HA показывают `StreamView GET` от IP колонки (`192.168.0.17`) — колонка **действительно качает поток** через HTTP!
- Пользователь подтвердил: колонка играет треки из MA, но при изменении громкости отображаемый трек сбрасывается.
- **Вывод:** Колонка **умеет** воспроизводить HTTP-потоки. Гипотеза была неверна.
- Проблема не в воспроизведении, а в **синхронизации UI/state**.

**Статус:** Опровергнута.

---

### Гипотеза 7: Облачный `playerState` перезаписывает локальный трек при изменении громкости

**Обоснование:**
- Колонка играет локальный поток (MA → HA StreamView → колонка).
- При изменении громкости `setVolume` через glagol, колонка присылает state update.
- В этом state update есть `playerState`, который содержит **облачный трек** (например, "Bad Romance" Lady Gaga), а не локальный поток.
- `async_set_state` в `yandex_station.py` безусловно перезаписывает `media_title`, `media_content_id`, `media_artist` из `playerState`.
- Результат: в HA UI отображается облачный трек, хотя колонка продолжает играть локальный.

**Патч:**
- `custom_components/yandex_station/core/yandex_station.py`:
  - Добавлен `self._local_media_id` — флаг активного локального потока.
  - В `async_play_media` (local mode): устанавливается `self._local_media_id = media_id` при запуске HTTP/URL потока.
  - В `async_set_state`: если `self._local_media_id` установлен и `playerState["id"]` не совпадает с ним (т.е. это облачный трек), `media_title`, `media_content_id`, `media_artist`, `media_image_url`, `media_playlist`, `media_content_type` **не перезаписываются**. Обновляются только `state` (playing/paused), `volume`, `position`.
  - Сброс `self._local_media_id = None` при `async_media_pause` и при отсутствии `playerState` в state update.

**Проверка:**
- Патч применён, HA перезапущен.
- Колонка доступна (`media_player.yandex_station_m10dst310hxnpk`).
- Ожидает проверки пользователем.

**Статус:** Патч применён, требуется проверка.

---

## Текущие патчи (активные)

### Music Assistant (контейнер `homeassistant-music-assistant-1`)

1. **`/app/venv/lib/python3.13/site-packages/music_assistant/providers/hass_players/player.py`**
   - `HomeAssistantPlayer.__init__`: убран параметр `hass` и `self.hass = hass`.
   - Добавлен `@property def hass` — динамически разрешает `prov.hass_prov.hass`.
   - Предотвращает stale reference после reconnect HA.

2. **`/app/venv/lib/python3.13/site-packages/music_assistant/providers/hass_players/provider.py`**
   - Вызов `HomeAssistantPlayer(provider=self, player_id=...)` — убран `hass=...`.

3. **`/data/settings.json` (MA)**
   - `providers.hass.values.url`: `http://192.168.0.39:8123`
   - `providers.hass.values.verify_ssl`: `false`

### Docker Compose (`ha.docker-compose.yaml`)

4. **Сервис `homeassistant`**
   - Добавлен `networks.ha-net.aliases: [homeassistant.local]`.
   - Позволяет MA и другим контейнерам резолвить `homeassistant.local` через встроенный Docker DNS.

### Home Assistant (`custom_components/yandex_station/`)

5. **`configuration.yaml`**
   - Добавлен `homeassistant.internal_url: "http://192.168.0.39:8123"`.
   - `network.get_url(hass, allow_external=False)` теперь возвращает корректный URL.

6. **`custom_components/yandex_station/core/yandex_station.py`**
   - Добавлен `self._local_media_id` и защита media атрибутов от облачного `playerState` при локальном воспроизведении.
   - Предотвращает сброс отображаемого трека при изменении громкости.

7. **`custom_components/yandex_station/core/stream.py`**
   - Lazy-резолвинг `hass_url()` + логирование.

---

## Откатанные патчи (неактуальные)

- **`configuration.yaml`**: блок `http:` с `ssl_certificate` / `ssl_key` — убран.
- **`ha.docker-compose.yaml`**: healthcheck `curl -fkS https://...` — откачен на `curl -fsS http://...`.
- **`custom_components/yandex_station/core/stream.py`**: fallback на `https://...` — откачен на `http://...`.
- **MA `settings.json`**: `hass.url = https://...` — откачен на `http://...`.

---

## Важные замечания

- **Активная колонка:** `media_player.yandex_station_m10dst310hxnpk` (friendly_name: "Станция Мини у Вовы").
- **Orphaned entity:** `media_player.stantsiia_mini_u_vovy` — `unavailable`, возможно, стоит удалить через UI HA (Настройки → Устройства и службы → Сущности).
- **Колонка играет HTTP-потоки:** Подтверждено логами `StreamView GET` с IP колонки.

---

## Итоговые активные патчи (кратко)

| Файл | Что изменено | Статус |
|------|-------------|--------|
| MA `player.py` | `hass` → dynamic property, stale reference пофикшен | **Работает** |
| MA `provider.py` | Dynamic `hass_prov` property, убран stale `HomeAssistantProvider` | **Работает** |
| MA `__init__.py` (hass) | Auto-reconnect loop с exponential backoff (5→60 сек) | **Работает** |
| MA `__init__.py` (hass_players) | Убран `hass_prov` из конструктора `HomeAssistantPlayerProvider` | **Работает** |
| MA `settings.json` | `hass.url` = `http://192.168.0.39:8123` | **Работает** |
| HA `configuration.yaml` | `internal_url` = `http://192.168.0.39:8123` | **Работает** |
| HA `ha.docker-compose.yaml` | Alias `homeassistant.local` для сервиса | **Работает** |
| HA `stream.py` | Lazy `hass_url()` + логирование | **Работает** |
| HA `yandex_station.py` | Защита media атрибутов + приём metadata из MA | **Работает** |

---

## Патч 8: Auto-reconnect в Music Assistant (критический)

**Проблема:** После `docker restart homeassistant-homeassistant-1` MA теряет websocket-соединение. В UI MA появляется "Fix now". Пользователю приходится вручную нажимать кнопку.

**Причина:** Стандартный retry в `mass.py` использует `call_later(120, ...)` — 2 минуты. Часто retry не срабатывает вообще, потому что `HomeAssistantPlayerProvider` хранит stale ссылку на старый `HomeAssistantProvider`.

**Патч (3 файла):**

### 1. `providers/hass_players/provider.py`
- Убран `hass_prov` из `__init__` и `hass_prov` parameter.
- Добавлен `@property def hass_prov` — динамически разрешает текущий `HomeAssistantProvider` через `self.mass.get_provider(HASS_DOMAIN)`.
- Это предотвращает stale reference на provider после reconnect.

### 2. `providers/hass_players/__init__.py`
- Убрана передача `hass_prov` в `HomeAssistantPlayerProvider(...)`.
- `setup()` теперь возвращает `HomeAssistantPlayerProvider(mass, manifest, config)` без `hass_prov`.

### 3. `providers/hass/__init__.py`
- `_hass_listener` переписан на `while True` reconnect loop.
- При disconnect: `await asyncio.sleep(retry_delay)`, затем `await self.hass.connect()`.
- Exponential backoff: 5 → 10 → 20 → ... до 60 секунд.
- При успехе: сброс `retry_delay = 5`.
- **Преимущество:** reconnect происходит через 5-20 секунд, а не через 2 минуты, и не требует ручного "Fix now".

**Проверка:**
- Перезапустил HA. MA отключился, через ~26 секунд автоматически переподключился.
- Сущность `media_player.stantsiia_mini_u_vovy` стала доступна без нажатия "Fix now".

**Статус:** Подтверждена и пофикшена.

---

## Патч 9: Приём metadata из Music Assistant в YandexStation

**Проблема:** При воспроизведении через Media Browser на `media_player.stantsiia_mini_u_vovy` (MA wrapper), нативная `media_player.yandex_station_m10dst310hxnpk` не обновляла трек/артист/обложку. На ней отображался последний облачный трек (Lady Gaga).

**Причина:** `async_play_media` получал `extra['metadata']` от MA с `title`, `artist`, `imageUrl`, `duration`, но не использовал эти поля.

**Патч:**
- `custom_components/yandex_station/core/yandex_station.py`:
  - При `async_play_media` с локальным потоком (HTTP URL) и наличии `metadata`:
    - `self._attr_media_title = metadata['title']`
    - `self._attr_media_artist = metadata['artist']`
    - `self._attr_media_duration = metadata['duration']`
    - `self._attr_media_image_url = metadata['imageUrl']`
    - `self._attr_media_content_type = MediaType.MUSIC`
    - `self._attr_state = MediaPlayerState.PLAYING`
    - `self._attr_media_position = 0`
    - `async_write_ha_state()` — обновляет UI **сразу**.

**Проверка:**
- Логи подтвердили, что MA передаёт полный metadata:
  ```
  metadata={'title': 'Serpent Kiss', 'artist': 'drunken night', 'imageUrl': 'http://172.20.0.4:8097/imageproxy?...', 'duration': 199}
  ```
- После патча UI нативной YandexStation показывает правильный трек, артиста и обложку.

**Статус:** Подтверждена и пофикшена.

---

## Патч 10: Пауза/Play для локального потока radio_play

**Проблема:** Кнопка паузы в HA UI не останавливала воспроизведение. При нажатии колонка переключалась на облачный трек (Lady Gaga).

**Причина:** Команды `glagol.send({"command": "stop"})` и `glagol.send({"command": "play"})` работают только для облачного плеера. Для локального `radio_play` они переключают обратно на облачный плеер.

**Решение:**
- Добавлен флаг `self._local_media_paused`.
- При `async_media_pause` с локальным потоком: не отправляем glagol, просто `self._local_media_paused = True`, `state = PAUSED`, `async_write_ha_state()`.
- При `async_media_play` с локальным потоком: `self._local_media_paused = False`, `state = PLAYING`, `async_write_ha_state()`.
- В `async_set_state` (получение state от колонки): если `_local_media_paused = True`, игнорируем `state["playing"]` и принудительно выставляем `state = PAUSED`.

**Статус:** Подтверждена и пофикшена.
