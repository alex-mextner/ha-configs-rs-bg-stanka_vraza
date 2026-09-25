"""Wakeword Studio: authenticated backend for the voice-collection UI.

Everything the Studio card needs goes through Home Assistant auth:
live microphone state (level, XVF-3000 direction, voice detection), the
background-noise recording session, wake-phrase candidates screened against
household transcripts, guided phrase recording sessions, and review of the
recorded clips. Audio is streamed only through an authenticated view (the
card uses signed paths), never from /local, which HA serves without auth.

Data lives in the shared dataset directory (host /home/ultra/oww-dataset,
/config/oww-dataset here); scripts/ provides the recorder tooling.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)
DOMAIN = "wakeword_studio"
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)
DATASET = Path("/config/oww-dataset")
SCRIPTS = Path("/config/scripts")
BINS = 36
SLOW_CACHE_SECONDS = 5.0
PHRASE_MAX_LEN = 60


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _age(updated_at: str | None) -> float | None:
    if not updated_at:
        return None
    try:
        t = dt.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    return max(0.0, (_now() - t).total_seconds())


# ---------------------------------------------------------------- phonetics
# Coarse Russian phonetic key: voicing pairs merged, vowels reduced the way
# unstressed Russian vowels sound, soft/hard signs dropped. Same rules as
# wakeword tooling phrase_screen.py, so UI numbers match offline reports.
_VOICING = str.maketrans({"б": "п", "в": "ф", "г": "к", "д": "т", "ж": "ш", "з": "с", "щ": "ш",
                          "ё": "а", "о": "а", "я": "а", "э": "е", "ы": "и", "ю": "у", "й": "и",
                          "ъ": None, "ь": None})


def phonetic_key(text: str) -> str:
    t = re.sub(r"[^а-яё]", "", text.lower().replace("ё", "е"))
    t = t.replace("дж", "ч").replace("тс", "ц").replace("тьс", "ц")
    t = t.translate(_VOICING)
    return re.sub(r"(.)\1+", r"\1", t)


def _lev(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _syllables(phrase: str) -> int:
    return len(re.findall(r"[аеёиоуыэюя]", phrase.lower()))


def screen_phrase(phrase: str, near: float = 0.25, close: float = 0.2) -> dict[str, Any]:
    """Count phonetic near-matches of `phrase` in household transcripts."""
    tdir = DATASET / "transcripts"
    meta = _read_json(tdir / "meta.json", {}) or {}
    ck = phonetic_key(phrase)
    n_words = len(phrase.split())
    hits_close = hits_near = utterances = 0
    examples: list[dict[str, Any]] = []
    files: set[str] = set()
    for path in sorted(tdir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                files.add(row.get("file", ""))
                text = row.get("text")
                if not text or not ck:
                    continue
                utterances += 1
                words = re.findall(r"[а-яёА-ЯЁ]+", text)
                keys = [phonetic_key(w) for w in words]
                best = None
                for width in {max(1, n_words - 1), n_words, n_words + 1}:
                    for i in range(max(1, len(words) - width + 1)):
                        wk = "".join(keys[i:i + width])
                        if not wk or abs(len(wk) - len(ck)) > max(2, len(ck) // 2):
                            continue
                        d = _lev(ck, wk) / len(ck)
                        if best is None or d < best[0]:
                            best = (d, " ".join(words[i:i + width]))
                if best and best[0] <= near:
                    hits_near += 1
                    hits_close += best[0] <= close
                    if len(examples) < 8:
                        examples.append({"match": best[1], "distance": round(best[0], 3),
                                         "context": text[:120], "utc": row.get("utc")})
    hours = float(meta.get("hours") or len(files) / 60.0)
    per_hour = hits_near / hours if hours else None
    syl = _syllables(phrase)
    phonemes = len(ck)
    if per_hour is None:
        verdict = "unknown"
    elif per_hour >= 0.2 or syl < 3:
        verdict = "bad"
    elif per_hour > 0.02 or phonemes < 6:
        verdict = "risky"
    else:
        verdict = "good"
    return {
        "phrase": phrase, "key": ck, "syllables": syl, "phonemes_approx": phonemes,
        "hours": round(hours, 1), "utterances": utterances,
        "near_hits": hits_near, "close_hits": hits_close,
        "near_per_hour": round(per_hour, 3) if per_hour is not None else None,
        "verdict": verdict, "examples": sorted(examples, key=lambda e: e["distance"]),
        "screened_at": _now().isoformat(),
    }


# ---------------------------------------------------------------- review
def _clip_id(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def list_clips() -> list[dict[str, Any]]:
    root = DATASET / "positives" / "real_user"
    status = (_read_json(DATASET / "review" / "status.json", {}) or {}).get("items", {})
    clips = []
    for wav in root.glob("*/*.wav") if root.exists() else []:
        try:
            st = wav.stat()
        except OSError:
            continue
        if st.st_size <= 44:
            continue
        rel = str(wav.relative_to(root))
        meta = _read_json(wav.with_suffix(".json"), {}) or {}
        cid = _clip_id(rel)
        review = status.get(cid, {})
        clips.append({
            "id": cid,
            "rel": rel,
            "session": meta.get("session_id") or wav.parent.name.split("_")[0],
            "phrase": meta.get("phrase"),
            "speaker": meta.get("speaker"),
            "style": meta.get("style"),
            "location": meta.get("location"),
            "duration": meta.get("duration_seconds") or round((st.st_size - 44) / 32000, 2),
            "level_max_dbfs": meta.get("level_max_dbfs"),
            "noise_floor_dbfs": meta.get("noise_floor_dbfs"),
            "doa_degrees": meta.get("doa_degrees"),
            "created_at": meta.get("created_at") or dt.datetime.fromtimestamp(st.st_mtime, dt.UTC).isoformat(),
            "status": review.get("status", "pending"),
        })
    clips.sort(key=lambda c: c["created_at"], reverse=True)
    return clips


def clip_path(cid: str) -> Path | None:
    root = DATASET / "positives" / "real_user"
    for wav in root.glob("*/*.wav") if root.exists() else []:
        if _clip_id(str(wav.relative_to(root))) == cid:
            return wav
    return None


def set_review(cid: str, status: str, user: str | None) -> dict[str, Any]:
    path = DATASET / "review" / "status.json"
    data = _read_json(path, {}) or {}
    items = data.setdefault("items", {})
    if status == "pending":
        items.pop(cid, None)
    else:
        items[cid] = {"status": status, "updated_at": _now().isoformat(), "user": user}
    data["updated_at"] = _now().isoformat()
    _write_json(path, data)
    return items.get(cid, {"status": "pending"})


# ---------------------------------------------------------------- live state
def array_state() -> dict[str, Any]:
    tee = _read_json(DATASET / "wakeword_array_status.json", {}) or {}
    doa = _read_json(DATASET / "wakeword_doa.json", {}) or {}
    tee_age, doa_age = _age(tee.get("updated_at")), _age(doa.get("updated_at"))
    chip_ok = doa_age is not None and doa_age <= 3.0
    return {
        "capture_ok": tee_age is not None and tee_age <= 5.0,
        "capture_age": None if tee_age is None else round(tee_age, 1),
        "level_dbfs": tee.get("level_dbfs"),
        "channel_rms": tee.get("channel_rms"),
        "direction_source": "xvf3000_doa" if chip_ok else "unavailable",
        "direction_degrees": doa.get("direction_degrees") if chip_ok else None,
        "voice_activity": doa.get("voice_activity") if chip_ok else None,
        "speech_detected": doa.get("speech_detected") if chip_ok else None,
        "speech_trail_degrees": doa.get("speech_trail_degrees") if chip_ok else [],
        "agc_on": doa.get("agc_on"),
        "agc_gain": doa.get("agc_gain"),
    }


def slow_state() -> dict[str, Any]:
    noise = _read_json(DATASET / "noise_session_status.json", {}) or {}
    noise["status_age_seconds"] = _age(noise.get("updated_at"))
    stats = _read_json(DATASET / "wakeword_doa_stats.json", {}) or {}
    cutoff = (_now() - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H")
    hist = [0] * BINS
    for hour, counts in (stats.get("hours") or {}).items():
        if hour >= cutoff and isinstance(counts, list) and len(counts) == BINS:
            hist = [a + b for a, b in zip(hist, counts)]
    phrase_dir = DATASET / "phrase"
    positive = _read_json(DATASET / "positive_sessions" / "current.json")
    captured = 0
    if positive and positive.get("output_dir"):
        out = Path(str(positive["output_dir"]).replace("/dataset/", "/config/oww-dataset/"))
        captured = len([p for p in out.glob("*.wav") if p.stat().st_size > 44]) if out.exists() else 0
    clips = list_clips()
    counts: dict[str, int] = {}
    speakers: dict[str, int] = {}
    for c in clips:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
        if c["status"] != "rejected" and c.get("speaker"):
            speakers[c["speaker"]] = speakers.get(c["speaker"], 0) + 1
    return {
        "noise": noise,
        "doa_hist_24h": {"bin_degrees": 360 // BINS, "counts": hist},
        "phrase": {
            "selected": _read_json(phrase_dir / "selected.json"),
            "candidates": _read_json(phrase_dir / "candidates.json", []) or [],
            "transcripts": _read_json(DATASET / "transcripts" / "meta.json", {}),
        },
        "positive": {"active": bool(positive), "session": positive, "captured": captured},
        "review": {"total": len(clips), "by_status": counts, "by_speaker": speakers},
        "room": _read_json(DATASET / "room.json", {"zones": []}) or {"zones": []},
        "training": training_state(),
    }


def training_state() -> dict[str, Any]:
    """Pipeline progress written every minute by wakeword pipeline_status.py (host cron)."""
    status = _read_json(DATASET / "training" / "status.json", {}) or {}
    status["status_age_seconds"] = _age(status.get("updated_at"))
    for p in status.get("pipelines", []):
        p.pop("notified", None)
    return status


class _Base(HomeAssistantView):
    requires_auth = True

    def __init__(self, hass: HomeAssistant, store: dict[str, Any]) -> None:
        self.hass = hass
        self.store = store

    async def job(self, fn, *args):
        return await self.hass.async_add_executor_job(fn, *args)

    @staticmethod
    async def body(request: web.Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def run_script(self, *argv: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "python3", *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 60)
        self.store["slow_at"] = 0.0  # refresh cached state on the next poll
        return proc.returncode or 0, out.decode("utf-8", "replace")[-2000:]


class StateView(_Base):
    url = "/api/wakeword_studio/state"
    name = "api:wakeword_studio:state"

    async def get(self, request: web.Request) -> web.Response:
        if time.monotonic() - self.store.get("slow_at", 0.0) > SLOW_CACHE_SECONDS:
            self.store["slow"] = await self.job(slow_state)
            self.store["slow_at"] = time.monotonic()
        return self.json({"now": _now().isoformat(), "array": await self.job(array_state), **self.store["slow"]})


class NoiseView(_Base):
    url = "/api/wakeword_studio/noise"
    name = "api:wakeword_studio:noise"

    async def post(self, request: web.Request) -> web.Response:
        action = (await self.body(request)).get("action")
        if action not in ("start", "stop"):
            return self.json_message("action must be start or stop", 400)
        argv = [str(SCRIPTS / "wakeword_noise_watchdog.py"), "--dataset-root", str(DATASET),
                "--session-file", str(DATASET / "raw_live_session.json"), action]
        code, out = await self.run_script(*argv)
        return self.json({"ok": code == 0, "output": out}, 200 if code == 0 else 409)


class PhraseView(_Base):
    url = "/api/wakeword_studio/phrase"
    name = "api:wakeword_studio:phrase"

    async def post(self, request: web.Request) -> web.Response:
        data = await self.body(request)
        action = data.get("action")
        phrase = re.sub(r"\s+", " ", str(data.get("phrase", ""))).strip()
        if action in ("screen", "select") and not (0 < len(phrase) <= PHRASE_MAX_LEN):
            return self.json_message("phrase must be 1-60 characters", 400)
        pdir = DATASET / "phrase"
        user = request.get("hass_user")
        who = user.name if user else None
        if action == "screen":
            result = await self.job(screen_phrase, phrase)
            candidates = await self.job(_read_json, pdir / "candidates.json", [])
            candidates = [c for c in (candidates or []) if c.get("phrase", "").lower() != phrase.lower()]
            candidates.insert(0, result)
            await self.job(_write_json, pdir / "candidates.json", candidates[:40])
            self.store["slow_at"] = 0.0
            return self.json(result)
        if action == "select":
            selected = {"phrase": phrase, "key": phonetic_key(phrase), "selected_at": _now().isoformat(), "by": who}
            await self.job(_write_json, pdir / "selected.json", selected)
            self.store["slow_at"] = 0.0
            return self.json(selected)
        if action == "unselect":
            await self.job(lambda: (pdir / "selected.json").unlink(missing_ok=True))
            self.store["slow_at"] = 0.0
            return self.json({"ok": True})
        if action == "forget":
            candidates = await self.job(_read_json, pdir / "candidates.json", [])
            candidates = [c for c in (candidates or []) if c.get("phrase", "").lower() != phrase.lower()]
            await self.job(_write_json, pdir / "candidates.json", candidates)
            self.store["slow_at"] = 0.0
            return self.json({"ok": True})
        return self.json_message("unknown action", 400)


class PositiveView(_Base):
    url = "/api/wakeword_studio/positive"
    name = "api:wakeword_studio:positive"

    async def post(self, request: web.Request) -> web.Response:
        data = await self.body(request)
        action = data.get("action")
        base = [str(SCRIPTS / "wakeword_real_positive_session.py"), "--dataset-root", str(DATASET),
                "--debug-root", "/config/wyoming-debug"]
        if action == "start":
            selected = await self.job(_read_json, DATASET / "phrase" / "selected.json")
            if not selected:
                return self.json_message("Сначала выберите фразу", 409)
            if await self.job(lambda: (DATASET / "positive_sessions" / "current.json").exists()):
                return self.json_message("Сессия уже идёт", 409)
            clean = {k: re.sub(r"[^0-9A-Za-zА-Яа-яЁё _.-]", "", str(data.get(k, "")))[:40].strip() or d
                     for k, d in (("speaker", "speaker"), ("style", "normal"), ("location", "room"))}
            expected = max(1, min(200, int(data.get("expected") or 20)))
            argv = base + ["start", "--phrase", selected["phrase"], "--speaker", clean["speaker"],
                           "--style", clean["style"], "--location", clean["location"],
                           "--expected-attempts", str(expected)]
        elif action == "finish":
            argv = base + ["finish"]
        else:
            return self.json_message("action must be start or finish", 400)
        code, out = await self.run_script(*argv)
        return self.json({"ok": code == 0, "output": out}, 200 if code == 0 else 409)


class ReviewView(_Base):
    url = "/api/wakeword_studio/review"
    name = "api:wakeword_studio:review"

    async def get(self, request: web.Request) -> web.Response:
        return self.json({"clips": await self.job(list_clips)})

    async def post(self, request: web.Request) -> web.Response:
        data = await self.body(request)
        status = data.get("status")
        cid = str(data.get("id", ""))
        if status not in ("confirmed", "rejected", "pending") or not re.fullmatch(r"[0-9a-f]{16}", cid):
            return self.json_message("bad id or status", 400)
        user = request.get("hass_user")
        result = await self.job(set_review, cid, status, user.name if user else None)
        self.store["slow_at"] = 0.0
        return self.json({"id": cid, **result})


ZONE_KINDS = ("people", "tv", "speaker", "other")


class RoomView(_Base):
    """Named directions around the array (sofa, TV, ...), used by the UI and,
    later, by the wake chain to distrust detections from media directions."""

    url = "/api/wakeword_studio/room"
    name = "api:wakeword_studio:room"

    async def post(self, request: web.Request) -> web.Response:
        zones_in = (await self.body(request)).get("zones")
        if not isinstance(zones_in, list) or len(zones_in) > 12:
            return self.json_message("zones must be a list of up to 12 items", 400)
        zones = []
        for z in zones_in:
            try:
                name = re.sub(r"\s+", " ", str(z["name"])).strip()[:30]
                center = int(round(float(z["center"]))) % 360
                width = max(10, min(120, int(round(float(z.get("width", 40))))))
            except (KeyError, TypeError, ValueError):
                return self.json_message("each zone needs name and center", 400)
            kind = z.get("kind") if z.get("kind") in ZONE_KINDS else "other"
            if name:
                zones.append({"name": name, "center": center, "width": width, "kind": kind})
        user = request.get("hass_user")
        room = {"zones": zones, "updated_at": _now().isoformat(), "by": user.name if user else None}
        await self.job(_write_json, DATASET / "room.json", room)
        self.store["slow_at"] = 0.0
        return self.json(room)


class AudioView(_Base):
    url = "/api/wakeword_studio/audio/{clip_id}"
    name = "api:wakeword_studio:audio"

    async def get(self, request: web.Request, clip_id: str) -> web.StreamResponse:
        if not re.fullmatch(r"[0-9a-f]{16}", clip_id):
            return self.json_message("bad id", 400)
        path = await self.job(clip_path, clip_id)
        if path is None:
            return self.json_message("not found", 404)
        return web.FileResponse(path, headers={"Content-Type": "audio/wav", "Cache-Control": "private, max-age=300"})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    store: dict[str, Any] = {"slow": {}, "slow_at": 0.0}
    for view in (StateView, NoiseView, PhraseView, PositiveView, ReviewView, RoomView, AudioView):
        hass.http.register_view(view(hass, store))
    _LOGGER.info("Wakeword Studio API registered at /api/wakeword_studio/*")
    return True
