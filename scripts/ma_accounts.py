#!/usr/bin/env python3
"""Music Assistant accounts per person and guest (aisis#17) - admin side.

Runs inside the Home Assistant container (music_assistant_client, /config mounted). The host
wrappers ytm-cookie, yandex-music-token and music-accounts call it and hold the MA
maintenance lock (/home/ultra/.ma-maintenance.lock) while it changes MA.

  list                                           people, accounts, MA users and their filters
  add ytmusic|yandex_music WHO [--device] [--dry-run]
                                                 create, or refresh, a person's account
  assign WHO --instance ID                       adopt an instance added in the MA UI
  unassign WHO [--provider D] [--delete]         forget (and optionally delete) an account
  rename WHO NAME                                display name used for instance names
  sync [--dry-run]                               instance names/options, MA users + filters
  expire [--dry-run]                             remove expired guests (instances + MA user)

WHO: --person <user-<id> | person.x | HA username | name> | --guest NAME [--days N] | --default

The mapping (no secrets) is /config/oww-dataset/voices/music_accounts.json, next to the voice
studio's guests.json and keyed by the same speaker ids (user-<HA user id>, guest-<slug>);
custom_components/music_accounts reads it. A cookie/token only arrives in env MA_SECRET (the
host wrapper reads it with hidden input); it goes into MA's setup flow and is never printed
or stored here (MA keeps it encrypted).

Why MA users with provider filters: MA 2.10 has one shared library; a user's provider_filter
steers search (music/search), streaming (streams/audio.py preferred_providers) and radio
refills to that user's instances, and Home Assistant's play_media/search accept `username`.
Unmapped MA users (HA integration, UI logins, party guest) follow the household default.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import datetime as dt
import hashlib
import html
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

import aiohttp
from music_assistant_client import MusicAssistantClient

MA_URL = "http://172.20.0.1:8095"
PO_TOKEN_SERVER = "http://127.0.0.1:4416"
VOICES = Path("/config/oww-dataset/voices")
MAPPING = VOICES / "music_accounts.json"
GUESTS = VOICES / "guests.json"
STORAGE = Path("/config/.storage")
SERVICES = {"ytmusic": "YouTube Music", "yandex_music": "Yandex Music"}
GUEST_LIBRARY_OFF = (
    "library_sync_artists",
    "library_sync_albums",
    "library_sync_tracks",
    "library_sync_playlists",
    "library_sync_podcasts",
    "library_sync_audiobooks",
)


class Fail(Exception):
    """A clean, user-facing error."""


def as_dict(obj: Any) -> Any:
    if isinstance(obj, list):
        return [as_dict(o) for o in obj]
    if isinstance(obj, dict) or obj is None:
        return obj
    return obj.to_dict() if hasattr(obj, "to_dict") else vars(obj)


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def studio_slug(text: str) -> str:
    """Same slug as custom_components/wakeword_studio (_slug) for guest speaker ids."""
    return re.sub(r"[^0-9a-zа-яё]+", "-", text.lower()).strip("-")[:30] or "guest"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def ha_people() -> list[dict[str, Any]]:
    """Household members: HA persons linked to an HA user (read-only view of .storage)."""
    persons = read_json(STORAGE / "person", {}).get("data", {}).get("items", [])
    auth = read_json(STORAGE / "auth", {}).get("data", {})
    usernames = {
        c["user_id"]: (c.get("data") or {}).get("username")
        for c in auth.get("credentials", [])
        if c.get("auth_provider_type") == "homeassistant"
    }
    owners = {u["id"] for u in auth.get("users", []) if u.get("is_owner")}
    return [
        {
            "speaker": f"user-{p['user_id']}",
            "entity": f"person.{p['id']}",
            "name": p["name"],
            "username": usernames.get(p["user_id"]),
            "owner": p["user_id"] in owners,
        }
        for p in persons
        if p.get("user_id")
    ]


def is_expired(entry: dict[str, Any]) -> bool:
    return bool(entry.get("expires_at")) and dt.datetime.fromisoformat(entry["expires_at"]) < now()


class Tool:
    def __init__(self, client: MusicAssistantClient, args: argparse.Namespace) -> None:
        self.c = client
        self.args = args
        self.dry = bool(getattr(args, "dry_run", False))
        self.mapping: dict[str, Any] = read_json(MAPPING, {}) or {}

    async def cmd(self, command: str, **kwargs: Any) -> Any:
        return as_dict(await self.c.send_command(command, **kwargs))

    # ------------------------------------------------------------------ state

    async def providers(self) -> list[dict[str, Any]]:
        return [p for p in await self.cmd("config/providers") if p.get("type") == "music"]

    async def users(self) -> list[dict[str, Any]]:
        return await self.cmd("auth/users")

    @property
    def people(self) -> dict[str, dict[str, Any]]:
        return self.mapping.setdefault("people", {})

    def save(self) -> None:
        self.mapping["version"] = 1
        if self.dry:
            print("dry run: mapping not written")
            return
        write_json(MAPPING, self.mapping)

    async def bootstrap(self) -> None:
        """First run: the existing single accounts become the owner's = household default."""
        if self.mapping.get("default"):
            return
        owner = next((p for p in ha_people() if p["owner"]), None)
        if owner is None:
            raise Fail("No HA owner person found to use as the household default")
        me = await self.cmd("auth/me")
        providers: dict[str, str] = {}
        for domain in SERVICES:
            instances = [p["instance_id"] for p in await self.providers() if p["domain"] == domain]
            if len(instances) == 1:
                providers[domain] = instances[0]
            elif len(instances) > 1:
                print(f"note: {len(instances)} {domain} instances, assign the default one by hand")
        self.mapping.update({"version": 1, "default": owner["speaker"]})
        self.people.setdefault(
            owner["speaker"],
            {"name": owner["name"], "ma_user": me["username"], "providers": providers},
        )
        print(f"household default = {owner['name']} ({owner['speaker']}), MA user {me['username']}")

    def who(self) -> tuple[str, dict[str, Any]]:
        """Resolve --person/--guest/--default to (speaker id, mapping entry template)."""
        a = self.args
        if getattr(a, "default", False):
            speaker = self.mapping.get("default")
            if not speaker:
                raise Fail("No household default yet")
            return speaker, self.people.get(speaker, {})
        if getattr(a, "guest", None):
            slug = studio_slug(a.guest)
            speaker = f"guest-{slug}"
            entry = dict(self.people.get(speaker) or {"name": a.guest.strip()[:40]})
            entry["guest"] = True
            # same lifetime rules as the studio's guest voices: 1-7 days, default 3; a guest
            # who already enrolled a voice keeps that expiry unless --days is given
            studio = (read_json(GUESTS, {}) or {}).get(slug) or {}
            if a.days:
                days = max(1, min(7, a.days))
                entry["expires_at"] = (now() + dt.timedelta(days=days)).isoformat()
            elif not entry.get("expires_at"):
                entry["expires_at"] = studio.get("expires_at") or (
                    now() + dt.timedelta(days=3)
                ).isoformat()
            return speaker, entry
        wanted = (getattr(a, "person", None) or "").strip()
        if not wanted:
            raise Fail("Say who: --person NAME, --guest NAME or --default")
        if wanted.startswith(("user-", "guest-")):
            return wanted, dict(self.people.get(wanted) or {"name": wanted})
        key = wanted.lower()
        for p in ha_people():
            if key in (p["entity"].lower(), (p["username"] or "").lower(), p["name"].lower()):
                return p["speaker"], dict(self.people.get(p["speaker"]) or {"name": p["name"]})
        for speaker, entry in self.people.items():
            if key == str(entry.get("name", "")).lower():
                return speaker, dict(entry)
        raise Fail(f"Unknown person {wanted!r} (HA persons: {', '.join(p['name'] for p in ha_people())})")

    # ------------------------------------------------------------------ flows

    async def _wait(self, flow_id: str, step: dict[str, Any], seconds: int) -> dict[str, Any]:
        shown = None
        for _ in range(seconds // 2):
            if step.get("type") != "progress":
                return step
            if step.get("image") and step["image"] != shown:
                shown = step["image"]
                self._show_device_code(step["image"])
            await asyncio.sleep(2)
            step = await self.cmd("config/flows/get", flow_id=flow_id)
        return step

    @staticmethod
    def _show_device_code(image: str) -> None:
        """The Yandex device step is an SVG with the address and the one-time code as text."""
        if not image.startswith("data:image/svg+xml;base64,"):
            print("Scan / confirm in the Music Assistant UI (Settings -> Providers).")
            return
        svg = base64.b64decode(image.split(",", 1)[1]).decode("utf-8", "replace")
        texts = [html.unescape(t) for t in re.findall(r"<text[^>]*>([^<]*)</text>", svg)]
        if len(texts) >= 4:
            print(f"\n  On the phone or computer of that person open  https://{texts[1]}")
            print(f"  sign in to THEIR Yandex account and enter the code:  {texts[3]}\n", flush=True)

    async def _abort(self, flow_id: str) -> None:
        with contextlib.suppress(Exception):  # best effort
            await self.cmd("config/flows/abort", flow_id=flow_id)

    async def run_flow(self, domain: str, instance: str | None) -> str | None:
        """Create (or reconfigure) an instance through MA's own setup flow; return its id."""
        if instance:
            step = await self.cmd("config/providers/reconfigure", instance_id=instance)
        else:
            step = await self.cmd("config/providers/setup", provider_domain=domain)
        flow_id = step.get("flow_id")
        what = f"refresh {instance}" if instance else f"create a new {domain} instance"
        if step.get("type") != "form" or not flow_id:
            raise Fail(f"MA refused to {what}: {step.get('type')} {step.get('reason') or ''}")
        if self.dry:
            await self._abort(flow_id)
            existing = [p["instance_id"] for p in await self.providers() if p["domain"] == domain]
            print(f"dry run: MA opened the flow to {what} (existing {domain}: {existing}); aborted")
            return None
        secret = os.environ.get("MA_SECRET", "")
        try:
            if domain == "ytmusic":
                values = {"username": "default", "cookie": secret, "po_token_server_url": PO_TOKEN_SERVER}
                step = await self.cmd("config/flows/submit", flow_id=flow_id, values=values)
                step = await self._wait(flow_id, step, 60)
            else:
                device = bool(self.args.device)
                step = await self.cmd(
                    "config/flows/submit",
                    flow_id=flow_id,
                    values={"method": "device" if device else "token", "remember_session": True},
                )
                if not device and step.get("type") == "form" and step.get("step_id") == "token_login":
                    step = await self.cmd(
                        "config/flows/submit", flow_id=flow_id, values={"token": secret}
                    )
                step = await self._wait(flow_id, step, 16 * 60 if device else 60)
        except BaseException:
            await self._abort(flow_id)
            raise
        if step.get("type") == "finish":
            return (step.get("result") or {}).get("instance_id") or instance
        await self._abort(flow_id)
        raise Fail(f"MA did not accept it: {step.get('errors') or step.get('reason') or step.get('type')}")

    # ------------------------------------------------------------------ commands

    async def add(self) -> int:
        domain = self.args.service
        await self.bootstrap()
        speaker, entry = self.who()
        existing = {p["instance_id"] for p in await self.providers()}
        instance = (entry.get("providers") or {}).get(domain)
        if instance not in existing:
            instance = None
        if not self.dry and domain == "ytmusic" and not os.environ.get("MA_SECRET"):
            raise Fail("No cookie given")
        if not self.dry and domain == "yandex_music" and not self.args.device and not os.environ.get("MA_SECRET"):
            raise Fail("No token given (or use --device)")
        new_id = await self.run_flow(domain, instance)
        if new_id is None:
            return 0
        entry.setdefault("providers", {})[domain] = new_id
        self.people[speaker] = entry
        print(f"{SERVICES[domain]} of {entry.get('name')}: {'refreshed' if instance else 'created'} {new_id}")
        self.save()
        await self.sync()
        return 0

    async def assign(self) -> int:
        await self.bootstrap()
        speaker, entry = self.who()
        conf = next((p for p in await self.providers() if p["instance_id"] == self.args.instance), None)
        if conf is None or conf["domain"] not in SERVICES:
            raise Fail(f"No YouTube Music / Yandex Music instance {self.args.instance}")
        for other, e in self.people.items():
            if other != speaker and self.args.instance in (e.get("providers") or {}).values():
                raise Fail(f"{self.args.instance} already belongs to {e.get('name')} ({other})")
        entry.setdefault("providers", {})[conf["domain"]] = conf["instance_id"]
        self.people[speaker] = entry
        print(f"{conf['instance_id']} -> {entry.get('name')} ({speaker})")
        self.save()
        await self.sync()
        return 0

    async def unassign(self) -> int:
        speaker, entry = self.who()
        if speaker not in self.people:
            raise Fail(f"{speaker} has no accounts")
        if speaker == self.mapping.get("default") and self.args.delete:
            raise Fail("Refusing to delete the household default's accounts")
        domains = [self.args.provider] if self.args.provider else list(entry.get("providers") or {})
        for domain in domains:
            instance = (entry.get("providers") or {}).pop(domain, None)
            if instance and self.args.delete:
                await self._remove_instance(instance)
        if not entry.get("providers") and speaker != self.mapping.get("default"):
            await self._remove_ma_user(entry)
            self.people.pop(speaker, None)
        else:
            self.people[speaker] = entry
        self.save()
        await self.sync()
        return 0

    async def rename(self) -> int:
        await self.bootstrap()
        speaker, entry = self.who()
        entry["name"] = self.args.name
        self.people[speaker] = entry
        self.save()
        await self.sync()
        return 0

    async def expire(self) -> int:
        expired = [s for s, e in self.people.items() if e.get("guest") and is_expired(e)]
        for speaker in expired:
            entry = self.people[speaker]
            print(f"guest {entry.get('name')} expired {entry.get('expires_at')}: removing")
            for instance in (entry.get("providers") or {}).values():
                await self._remove_instance(instance)
            await self._remove_ma_user(entry)
            self.people.pop(speaker)
        if expired:
            self.save()
        # hourly from cron: sync also picks up providers added in the MA UI into the filters
        return await self.sync()

    async def _remove_instance(self, instance: str) -> None:
        print(f"{'would remove' if self.dry else 'removing'} MA instance {instance}")
        if not self.dry:
            try:
                await self.cmd("config/providers/remove", instance_id=instance)
            except Exception as err:  # already gone is fine
                print(f"  ({err})")

    async def _remove_ma_user(self, entry: dict[str, Any]) -> None:
        name = entry.get("ma_user")
        if not name or not entry.get("ma_user_created"):
            return  # never delete an MA user this tool did not create
        user = next((u for u in await self.users() if u["username"] == name), None)
        if user:
            print(f"{'would delete' if self.dry else 'deleting'} MA user {name}")
            if not self.dry:
                await self.cmd("auth/user/delete", user_id=user["user_id"])

    # ------------------------------------------------------------------ sync

    async def sync(self) -> int:
        """Make MA match the mapping: names, per-instance options, MA users, filters."""
        await self.bootstrap()
        confs = {p["instance_id"]: p for p in await self.providers()}
        default_speaker = self.mapping.get("default")
        default = self.people.get(default_speaker or "", {})
        default_own = dict(default.get("providers") or {})
        changed = False

        # 1. instances: names, sync-back only on the default's Yandex, guests import nothing
        for speaker, entry in self.people.items():
            for domain, instance in (entry.get("providers") or {}).items():
                conf = confs.get(instance)
                if conf is None:
                    print(f"warning: {instance} of {entry.get('name')} does not exist in MA")
                    continue
                guest = bool(entry.get("guest"))
                name = f"{SERVICES[domain]} — {entry.get('name')}{' (гость)' if guest else ''}"
                want: dict[str, Any] = {}
                if conf.get("name") != name:
                    want["name"] = name
                current = await self._values(instance)
                if domain == "yandex_music" and speaker != default_speaker:
                    # MA forwards a library add to EVERY mapped Yandex account with sync-back
                    # on; only the household default keeps it, persons like via music_accounts
                    want.update(self._diff(current, {"library_sync_back": False}))
                if guest:
                    want.update(self._diff(current, dict.fromkeys(GUEST_LIBRARY_OFF, False)))
                if want:
                    changed = True
                    print(f"{instance}: set {want}")
                    if not self.dry:
                        await self.cmd(
                            "config/providers/save",
                            provider_domain=domain,
                            instance_id=instance,
                            values=want,
                        )

        # 2. MA users for persons with own accounts
        users = {u["username"]: u for u in await self.users()}
        for speaker, entry in self.people.items():
            if speaker == default_speaker or not entry.get("providers") or is_expired(entry):
                continue
            username = entry.get("ma_user") or self._ma_username(speaker, entry)
            if username in users:
                if entry.get("ma_user") != username:
                    # an MA user named like the HA user is that person (e.g. an HA login)
                    entry["ma_user"] = username
                    changed = True
                continue
            print(f"{'would create' if self.dry else 'creating'} MA user {username} for {entry.get('name')}")
            changed = True
            if not self.dry:
                await self.cmd(
                    "auth/user/create",
                    username=username,
                    # impersonation-only identity: nobody logs in with it, the password is
                    # random and deliberately not kept anywhere
                    password=secrets.token_urlsafe(32),
                    role="guest" if entry.get("guest") else "user",
                    display_name=f"{entry.get('name')}{' (гость)' if entry.get('guest') else ''}",
                )
                entry["ma_user"] = username
                entry["ma_user_created"] = True
                users = {u["username"]: u for u in await self.users()}

        # 3. provider filters
        owned = {i for e in self.people.values() for i in (e.get("providers") or {}).values()}
        foreign = owned - set(default_own.values())
        shared = [i for i in confs if i not in owned]
        person_users = {
            e["ma_user"]: e for s, e in self.people.items() if e.get("ma_user") and s != default_speaker
        }
        # filters this tool set last time; a filter someone changed by hand is left alone
        managed: dict[str, list[str]] = self.mapping.setdefault("filters", {})
        for username, user in users.items():
            if not user.get("enabled", True):
                continue
            if not foreign:
                want_filter: list[str] = []  # one account per service: nothing to steer
            elif username in person_users:
                own = dict(person_users[username].get("providers") or {})
                fallback = [i for d, i in default_own.items() if d not in own]
                want_filter = sorted({*shared, *own.values(), *fallback})
            else:
                # everybody else (HA integration, UI logins, party guest) = household default;
                # without a filter MA would pick whichever account of a service loaded first
                want_filter = sorted({*shared, *default_own.values()})
            current = sorted(user.get("provider_filter") or [])
            if current and current != sorted(managed.get(username) or []):
                print(f"MA user {username}: filter was set outside music-accounts, left alone")
                continue
            if current != want_filter:
                changed = True
                print(f"MA user {username}: provider filter {want_filter or 'none (all)'}")
                if not self.dry:
                    await self.cmd(
                        "auth/user/update", user_id=user["user_id"], provider_filter=want_filter
                    )
            if managed.get(username) != want_filter:
                managed[username] = want_filter
                changed = True
        if changed:
            self.save()
        else:
            print("in sync")
        return 0

    async def _values(self, instance: str) -> dict[str, Any]:
        conf = await self.cmd("config/providers/get", instance_id=instance)
        return {k: (v or {}).get("value") for k, v in (conf.get("values") or {}).items() if isinstance(v, dict)}

    @staticmethod
    def _diff(current: dict[str, Any], want: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in want.items() if k in current and current[k] != v}

    @staticmethod
    def _ma_username(speaker: str, entry: dict[str, Any]) -> str:
        if entry.get("guest"):
            return "guest_" + hashlib.sha1(speaker.encode()).hexdigest()[:8]
        person = next((p for p in ha_people() if p["speaker"] == speaker), None)
        username = (person or {}).get("username") or speaker.removeprefix("user-")[:12]
        return re.sub(r"[^a-z0-9_]+", "_", username.lower())

    # ------------------------------------------------------------------ list

    async def list(self) -> int:
        confs = {p["instance_id"]: p for p in await self.providers()}
        users = {u["username"]: u for u in await self.users()}
        default = self.mapping.get("default")
        mapped: set[str] = set()
        print(f"mapping: {MAPPING}{'' if MAPPING.exists() else ' (not created yet)'}")
        known = {p["speaker"]: p for p in ha_people()}
        for speaker in [*self.people, *[s for s in known if s not in self.people]]:
            entry = self.people.get(speaker, {"name": known[speaker]["name"]})
            tags = []
            if speaker == default:
                tags.append("household default")
            if entry.get("guest"):
                tags.append(f"guest until {entry.get('expires_at')}{' EXPIRED' if is_expired(entry) else ''}")
            print(f"\n{entry.get('name')}  [{speaker}]  {', '.join(tags)}")
            ma_user = entry.get("ma_user")
            if ma_user:
                flt = (users.get(ma_user) or {}).get("provider_filter")
                print(f"  MA user: {ma_user}{'' if ma_user in users else ' (missing)'}  filter: {flt or 'none (all)'}")
            own = entry.get("providers") or {}
            if not own:
                print("  no own accounts: plays from the household default, likes are refused")
            for domain, instance in own.items():
                mapped.add(instance)
                conf = confs.get(instance) or {}
                state = "OK" if conf and not conf.get("last_error") else (conf.get("last_error") or "MISSING")
                print(f"  {SERVICES.get(domain, domain)}: {instance}  {conf.get('name') or ''}  [{state}]")
        rest = [i for i, c in confs.items() if c["domain"] in SERVICES and i not in mapped]
        if rest:
            print(f"\nunassigned: {', '.join(rest)}  (music-accounts assign --person NAME --instance ID)")
        others = [u for u in users if u not in {e.get('ma_user') for e in self.people.values()}]
        print(f"\nother MA users (follow the household default): {', '.join(others)}")
        return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="music-accounts", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def who(p: argparse.ArgumentParser) -> None:
        g = p.add_mutually_exclusive_group()
        g.add_argument("--person", help="user-<id>, person.x, HA username or name")
        g.add_argument("--guest", help="guest name (speaker guest-<slug> as in the voice studio)")
        g.add_argument("--default", action="store_true", help="the household default")
        p.add_argument("--days", type=int, help="guest lifetime in days (1-7, default 3)")

    sub.add_parser("list")
    p = sub.add_parser("add")
    p.add_argument("service", choices=list(SERVICES))
    who(p)
    p.add_argument("--device", action="store_true", help="Yandex: sign in with a code on ya.ru/device")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("assign")
    who(p)
    p.add_argument("--instance", required=True)
    p = sub.add_parser("unassign")
    who(p)
    p.add_argument("--provider", choices=list(SERVICES))
    p.add_argument("--delete", action="store_true", help="also delete the MA instance")
    p = sub.add_parser("rename")
    who(p)
    p.add_argument("name")
    p = sub.add_parser("sync")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("expire")
    p.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


async def main(argv: list[str]) -> int:
    args = parse_args(argv)
    async with aiohttp.ClientSession() as session:
        client = MusicAssistantClient(MA_URL, session, token=os.environ["MA_TOKEN"])
        await client.connect()
        try:
            tool = Tool(client, args)
            return await getattr(tool, args.command)()
        except Fail as err:
            print(err, file=sys.stderr)
            return 1
        finally:
            await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
