#!/usr/bin/env python3
"""OpenAI-compatible bridge from OpenClaw to the ChatGPT web UI (chatgpt.com, subscription).

A dedicated Chrome profile runs headed on a private X display. The user signs in and completes any
human check themselves through noVNC. The bridge never reads cookies or tokens, never calls private
ChatGPT HTTP APIs, never patches or disguises the browser and never solves challenges: when ChatGPT
wants a human, requests fail with 503 and Home Assistant gets a notification.

Tools are emulated in the prompt. The model answers with one ```tool_calls``` JSON block, which the
bridge returns as OpenAI `tool_calls`. A conversation stays in its own browser tab (temporary chat),
so follow-up requests whose history extends a previous answer only send the new messages.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field

HOME = "https://chatgpt.com/"
MODEL_ID = "chatgpt-web"

COMPOSER = '#prompt-textarea[contenteditable="true"], textarea#prompt-textarea'
SEND = '[data-testid="send-button"]'
STOP = '[data-testid="stop-button"]'
ASSISTANT = '[data-message-author-role="assistant"]'
COPY = '[data-testid="copy-turn-action-button"]'
CHALLENGE = re.compile(r"verify you are human|checking your browser|just a moment|подтвердите, что вы человек", re.I)
LOGIN = re.compile(r"^(log in|sign in|sign up for free|войти|зарегистрироваться)$", re.I)
LIMIT = re.compile(r"(?:you.ve (?:hit|reached)|you have reached).{0,80}limit|too many requests|limit resets|"
                   r"достигнут.{0,40}лимит|лимит.{0,40}достигнут", re.I | re.S)

# Captures what ChatGPT's own "copy" button writes (the answer as markdown) without touching the
# system clipboard. Only affects pages of this dedicated profile.
COPY_HOOK = """
(() => {
  if (window.__cgwHooked || !navigator.clipboard) return;
  window.__cgwHooked = true;
  window.__cgwCopies = [];
  const keep = (t) => { window.__cgwCopies.push(String(t)); window.__cgwCopies.splice(0, window.__cgwCopies.length - 10); };
  navigator.clipboard.writeText = async (t) => { keep(t); };
  navigator.clipboard.write = async (items) => {
    for (const item of items) {
      if (item.types.includes('text/plain')) { keep(await (await item.getType('text/plain')).text()); return; }
    }
  };
})();
"""

# Fallback when the copy button is missing: rendered text with code blocks kept verbatim.
DOM_MARKDOWN = """
(el) => {
  const clone = el.cloneNode(true);
  clone.querySelectorAll('pre').forEach((pre) => {
    const code = pre.querySelector('code');
    const lang = code ? ([...code.classList].find((c) => c.startsWith('language-')) || '').slice(9) : '';
    const text = (code || pre).textContent.replace(/\\n$/, '');
    pre.replaceWith(document.createTextNode('\\n```' + lang + '\\n' + text + '\\n```\\n'));
  });
  clone.style.cssText = 'position:absolute;left:-100000px;top:0;width:900px;white-space:normal';
  document.body.appendChild(clone);
  const text = clone.innerText;
  clone.remove();
  return text;
}
"""

log = logging.getLogger("chatgpt-web")


class BridgeError(Exception):
    def __init__(self, message: str, status: int = 502, kind: str = "upstream_error"):
        super().__init__(message)
        self.status = status
        self.kind = kind


class NeedsHuman(BridgeError):
    def __init__(self, state: str):
        what = "a human check" if state == "challenge_required" else "a sign-in"
        super().__init__(f"ChatGPT web needs {what}: open the bridge's noVNC view and complete it yourself.",
                         503, state)
        self.state = state


# ---------------------------------------------------------------- prompt and reply (pure functions)

def content_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif part.get("type") in ("text", "input_text", "output_text"):
            parts.append(part.get("text", ""))
        else:
            parts.append(f"[{part.get('type', 'attachment')} omitted: the web bridge sends text only]")
    return "\n".join(parts)


def _args(raw) -> object:
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return raw
    return raw if raw is not None else {}


def canon(msg: dict) -> str:
    """Stable identity of one non-system message, used to recognise a continued conversation.
    Tool-call ids are left out: clients may rewrite them."""
    calls = [(c.get("function", {}).get("name"), _args(c.get("function", {}).get("arguments")))
             for c in msg.get("tool_calls") or []]
    return json.dumps([msg.get("role"), content_text(msg.get("content")).strip(), calls],
                      ensure_ascii=False, sort_keys=True)


def tool_names(tools) -> set[str]:
    return {t.get("function", {}).get("name") for t in tools or [] if t.get("type", "function") == "function"} - {None}


def render_tools(tools) -> str:
    lines = []
    for tool in tools or []:
        fn = tool.get("function", {})
        if not fn.get("name"):
            continue
        schema = json.dumps(fn.get("parameters") or {"type": "object", "properties": {}}, ensure_ascii=False,
                            separators=(",", ":"))
        lines.append(f"- {fn['name']}: {(fn.get('description') or '').strip()}\n  parameters: {schema}")
    return "\n".join(lines)


TOOL_RULES = """To call tools, reply with ONLY one fenced code block tagged tool_calls that holds a JSON array:
```tool_calls
[{"name": "tool_name", "arguments": {"param": "value"}}]
```
Several independent calls may go in the same array. Do not write anything outside that block when calling tools, never invent tool results, and wait for the TOOL RESULT messages. When no tool is needed, answer normally in plain text."""


def render_message(msg: dict) -> str:
    role = msg.get("role")
    text = content_text(msg.get("content")).strip()
    if role == "tool":
        label = " ".join(x for x in (msg.get("name"), msg.get("tool_call_id")) if x)
        return f"=== TOOL RESULT{' (' + label + ')' if label else ''} ===\n{text}"
    if role == "assistant":
        body = [text] if text else []
        calls = [{"name": c.get("function", {}).get("name"), "arguments": _args(c.get("function", {}).get("arguments"))}
                 for c in msg.get("tool_calls") or []]
        if calls:
            body.append("```tool_calls\n" + json.dumps(calls, ensure_ascii=False) + "\n```")
        return "=== ASSISTANT ===\n" + "\n".join(body)
    return f"=== {'USER' if role == 'user' else str(role).upper()} ===\n{text}"


def build_prompt(messages: list[dict], tools, delta: list[dict] | None = None) -> str:
    """Full prompt for a new chat, or only the new messages when continuing one."""
    if delta is not None:
        body = "\n\n".join(render_message(m) for m in delta)
        hint = " Call tools only with a tool_calls block." if tools else ""
        return f"{body}\n\n(Continue as the assistant: reply to the latest message.{hint})"
    system = "\n\n".join(content_text(m.get("content")).strip() for m in messages
                         if m.get("role") in ("system", "developer"))
    rest = [m for m in messages if m.get("role") not in ("system", "developer")]
    out = ["You are the language model behind an assistant API. Follow the SYSTEM instructions below, "
           "treat the conversation as the real dialogue so far and reply to its latest message as the assistant. "
           "Reply in the language the user writes in."]
    if system:
        out.append("=== SYSTEM ===\n" + system)
    if tools:
        out.append("=== TOOLS ===\n" + TOOL_RULES + "\n\nAvailable tools:\n" + render_tools(tools))
    out.extend(render_message(m) for m in rest)
    return "\n\n".join(out)


FENCE = re.compile(r"```[ \t]*([\w-]*)[ \t]*\n(.*?)\n?```", re.S)


def parse_reply(markdown: str, tools) -> tuple[str, list[dict]]:
    """Split the answer into plain text and tool calls. Only known tool names count as calls."""
    names = tool_names(tools)
    if not names:
        return markdown.strip(), []
    calls, spans = [], []
    for match in FENCE.finditer(markdown):
        lang, body = match.group(1).lower(), match.group(2).strip()
        if lang not in ("tool_calls", "tool_call", "json", ""):
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        found = []
        for item in items:
            if not isinstance(item, dict):
                break
            name = item.get("name") or item.get("tool") or (item.get("function") or {}).get("name")
            args = item.get("arguments", item.get("args", (item.get("function") or {}).get("arguments", {})))
            if name not in names:
                break
            found.append((name, _args(args)))
        else:
            if found:
                calls.extend(found)
                spans.append(match.span())
    text = markdown
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    tool_calls = [{"id": "call_" + secrets.token_hex(8), "type": "function",
                   "function": {"name": name, "arguments": json.dumps(args if isinstance(args, dict) else {"input": args},
                                                                     ensure_ascii=False)}}
                  for name, args in calls]
    return text.strip(), tool_calls


def match_conversation(histories: list[list[str]], request: list[str]) -> int | None:
    """Index of the longest stored history that the request strictly extends, else None."""
    best, best_len = None, -1
    for i, history in enumerate(histories):
        if history and len(history) < len(request) and request[:len(history)] == history and len(history) > best_len:
            best, best_len = i, len(history)
    return best


# ---------------------------------------------------------------- browser side

@dataclass
class Conversation:
    page: object
    history: list[str] = field(default_factory=list)
    used: float = field(default_factory=time.monotonic)


async def visible(locator) -> bool:
    try:
        for i in range(await locator.count()):
            if await locator.nth(i).is_visible():
                return True
    except Exception:
        return False
    return False


async def readiness(page) -> str:
    try:
        title = await page.title()
    except Exception:
        return "loading"
    if CHALLENGE.search(title) or await visible(page.get_by_text(CHALLENGE)):
        return "challenge_required"
    if not page.url.startswith(HOME):
        return "signin_required"
    if await visible(page.get_by_role("button", name=LOGIN)) or await visible(page.get_by_role("link", name=LOGIN)):
        return "signin_required"
    if await visible(page.locator(COMPOSER)):
        return "ready"
    return "loading"


class Browser:
    def __init__(self, profile: str, max_tabs: int, reply_timeout: float, temporary: bool, model_slug: str,
                 notifier):
        self.profile, self.max_tabs, self.reply_timeout = profile, max_tabs, reply_timeout
        self.temporary, self.model_slug, self.notifier = temporary, model_slug, notifier
        self.lock = asyncio.Lock()
        self.convs: list[Conversation] = []
        self.state = "starting"
        self.status_page = None

    async def start(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.ctx = await self.pw.chromium.launch_persistent_context(
            self.profile, channel="chrome", headless=False, viewport=None, accept_downloads=False,
            args=["--window-size=1280,900", "--window-position=0,0", "--no-first-run"])
        await self.ctx.add_init_script(COPY_HOOK)
        self.status_page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        await self.status_page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        await self.refresh_state()

    async def refresh_state(self, reload: bool = False) -> str:
        page = self.status_page
        if reload:
            await page.reload(wait_until="domcontentloaded", timeout=60000)
        state = "loading"
        for _ in range(40):
            state = await readiness(page)
            if state != "loading":
                await self.set_state(state)
                break
            await asyncio.sleep(0.5)
        return state

    async def set_state(self, state: str):
        if state == self.state:
            return
        log.info("state %s -> %s", self.state, state)
        self.state = state
        await self.notifier.state_changed(state)

    async def monitor(self):
        """Watch sign-in state: quickly while waiting for the user, a light reload every 30 min."""
        last_reload = time.monotonic()
        while True:
            await asyncio.sleep(15 if self.state != "ready" else 60)
            if self.lock.locked():
                continue
            try:
                async with self.lock:
                    reload = self.state == "ready" and time.monotonic() - last_reload > 1800
                    if reload:
                        last_reload = time.monotonic()
                    await self.refresh_state(reload=reload)
            except Exception as exc:
                log.warning("monitor: %s", exc)

    def chat_url(self) -> str:
        params = []
        if self.temporary:
            params.append("temporary-chat=true")
        if self.model_slug:
            params.append("model=" + self.model_slug)
        return HOME + ("?" + "&".join(params) if params else "")

    async def new_conversation(self) -> Conversation:
        live = [c for c in self.convs if not c.page.is_closed()]
        while len(live) >= self.max_tabs:
            oldest = min(live, key=lambda c: c.used)
            live.remove(oldest)
            await oldest.page.close()
        page = await self.ctx.new_page()
        await page.goto(self.chat_url(), wait_until="domcontentloaded", timeout=60000)
        for _ in range(60):
            state = await readiness(page)
            if state == "ready":
                break
            if state in ("challenge_required", "signin_required"):
                await page.close()
                await self.set_state(state)
                raise NeedsHuman(state)
            await asyncio.sleep(0.5)
        else:
            await page.close()
            raise BridgeError("ChatGPT page did not become ready (composer not found).")
        conv = Conversation(page)
        self.convs = live + [conv]
        return conv

    async def ask(self, page, prompt: str) -> str:
        answers = page.locator(ASSISTANT)
        before = await answers.count()
        composer = page.locator(COMPOSER)
        if await composer.count() != 1:
            raise BridgeError("ChatGPT composer changed; refusing blind input.")
        await composer.click()
        await composer.fill(prompt)
        send = page.locator(SEND)
        await send.wait_for(state="visible", timeout=15000)
        await send.click()
        deadline = time.monotonic() + self.reply_timeout
        started = time.monotonic()
        last, stable_since = None, 0.0
        while time.monotonic() < deadline:
            state = await readiness(page)
            if state in ("challenge_required", "signin_required"):
                await self.set_state(state)
                raise NeedsHuman(state)
            alerts = page.get_by_role("alert")
            for i in range(min(await alerts.count(), 4)):
                text = await alerts.nth(i).inner_text()
                if LIMIT.search(text):
                    raise BridgeError("ChatGPT usage limit reached: " + text.strip()[:300], 429, "rate_limited")
            if await answers.count() > before:
                text = await answers.last.inner_text()
                if await visible(page.locator(STOP)) or not text.strip():
                    last, stable_since = None, 0.0
                elif text != last:
                    last, stable_since = text, time.monotonic()
                elif time.monotonic() - stable_since > 1.5:
                    break
            elif time.monotonic() - started > 90 and not await visible(page.locator(STOP)):
                raise BridgeError("ChatGPT did not start answering; inspect the chat in noVNC.")
            await asyncio.sleep(0.5)
        else:
            raise BridgeError(f"No complete ChatGPT answer within {self.reply_timeout:.0f} s.", 504, "timeout")
        return await self.answer_markdown(page, answers.last)

    async def answer_markdown(self, page, answer) -> str:
        try:
            await page.evaluate("window.__cgwCopies = []")
            button = answer.locator("xpath=ancestor::article[1]").locator(COPY)
            if await button.count() == 0:
                button = page.locator(COPY)
            if await button.count():
                await answer.hover()
                await button.last.click(timeout=5000)
                for _ in range(30):
                    copies = await page.evaluate("window.__cgwCopies || []")
                    if copies and copies[-1].strip():
                        return copies[-1]
                    await asyncio.sleep(0.1)
        except Exception as exc:
            log.info("copy button unavailable (%s); using the rendered text", exc)
        return await answer.evaluate(DOM_MARKDOWN)

    async def complete(self, messages: list[dict], tools) -> dict:
        rest = [m for m in messages if m.get("role") not in ("system", "developer")]
        if not rest:
            raise BridgeError("No user message to answer.", 400, "invalid_request_error")
        request = [canon(m) for m in rest]
        if self.state in ("signin_required", "challenge_required"):
            # Fail fast without opening tabs over the window the user is signing in with.
            raise NeedsHuman(self.state)
        async with self.lock:
            self.convs = [c for c in self.convs if not c.page.is_closed()]
            index = match_conversation([c.history for c in self.convs], request)
            if index is not None:
                conv = self.convs[index]
                prompt = build_prompt(messages, tools, delta=rest[len(conv.history):])
            else:
                conv = await self.new_conversation()
                prompt = build_prompt(messages, tools)
            conv.used = time.monotonic()
            started = time.monotonic()
            try:
                markdown = await self.ask(conv.page, prompt)
            except BaseException:
                # The tab's state is unknown now; never continue it.
                conv.history = []
                raise
            text, calls = parse_reply(markdown, tools)
            reply = {"role": "assistant", "content": text or None}
            if calls:
                reply["tool_calls"] = calls
            conv.history = request + [canon(reply)]
            await self.set_state("ready")
            log.info("answered in %.1f s (%s, prompt %d chars, reply %d chars, %d tool calls)",
                     time.monotonic() - started, "continued" if index is not None else "new chat",
                     len(prompt), len(markdown), len(calls))
            return {"message": reply, "prompt_chars": len(prompt), "reply_chars": len(markdown)}


# ---------------------------------------------------------------- Home Assistant notification

class Notifier:
    NID = "chatgpt_web_bridge"

    def __init__(self, ha_url: str, ha_token: str):
        self.ha_url, self.ha_token = ha_url.rstrip("/"), ha_token

    async def call(self, service: str, payload: dict):
        if not self.ha_url or not self.ha_token:
            return
        import aiohttp
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                await session.post(f"{self.ha_url}/api/services/{service}", json=payload,
                                   headers={"Authorization": f"Bearer {self.ha_token}"})
        except Exception as exc:
            log.warning("HA notify failed: %s", exc)

    async def state_changed(self, state: str):
        if state in ("signin_required", "challenge_required"):
            what = "войти в ChatGPT" if state == "signin_required" else "пройти проверку «я человек»"
            message = (f"OpenClaw не может ответить через chatgpt.com: нужно {what}.\n\n"
                       "С компьютера: `ssh -N -L 6080:127.0.0.1:6080 root@home`, затем открыть "
                       "http://localhost:6080/vnc.html и сделать это в открытом окне Chrome.")
            await self.call("persistent_notification/create",
                            {"notification_id": self.NID, "title": "ChatGPT web: нужен человек", "message": message})
            await self.call("notify/notify", {"title": "ChatGPT web: нужен человек", "message": message})
        elif state == "ready":
            await self.call("persistent_notification/dismiss", {"notification_id": self.NID})


# ---------------------------------------------------------------- OpenAI-compatible HTTP API

def completion_payload(result: dict, model: str) -> dict:
    message = result["message"]
    return {
        "id": "chatcmpl-" + secrets.token_hex(12), "object": "chat.completion", "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message,
                     "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
        "usage": usage(result),
    }


def usage(result: dict) -> dict:
    prompt, completion = result["prompt_chars"] // 4, result["reply_chars"] // 4
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def stream_chunks(result: dict, model: str, include_usage: bool) -> list[dict]:
    base = {"id": "chatcmpl-" + secrets.token_hex(12), "object": "chat.completion.chunk",
            "created": int(time.time()), "model": model}
    message = result["message"]
    delta = {"role": "assistant"}
    if message.get("content"):
        delta["content"] = message["content"]
    if message.get("tool_calls"):
        delta["tool_calls"] = [dict(call, index=i) for i, call in enumerate(message["tool_calls"])]
    chunks = [dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
              dict(base, choices=[{"index": 0, "delta": {},
                                   "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}])]
    if include_usage:
        chunks.append(dict(base, choices=[], usage=usage(result)))
    return chunks


async def run(browser: Browser, messages, tools) -> dict:
    try:
        return await browser.complete(messages, tools)
    except BridgeError:
        raise
    except Exception as exc:
        log.exception("completion failed")
        raise BridgeError(f"Browser error: {str(exc)[:300]}") from None


def make_app(browser: Browser, api_key: str):
    from aiohttp import web

    def error(status: int, message: str, kind: str):
        return web.json_response({"error": {"message": message, "type": kind}}, status=status)

    @web.middleware
    async def auth(request, handler):
        if request.path.startswith("/v1/"):
            given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(given.encode(), api_key.encode()):
                return error(401, "Invalid API key.", "invalid_request_error")
        return await handler(request)

    async def health(_request):
        return web.json_response({"state": browser.state, "tabs": len(browser.convs), "busy": browser.lock.locked()})

    async def models(_request):
        return web.json_response({"object": "list", "data": [
            {"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "chatgpt-web"}]})

    async def chat(request):
        try:
            body = await request.json()
        except Exception:
            return error(400, "Body must be JSON.", "invalid_request_error")
        messages, tools = body.get("messages") or [], body.get("tools") or []
        if body.get("tool_choice") == "none":
            tools = []
        model = body.get("model") or MODEL_ID
        task = asyncio.create_task(run(browser, messages, tools))
        # Quick failures (sign-in needed, limits) get a real HTTP status, also for streaming clients.
        done, _ = await asyncio.wait({task}, timeout=8)
        if done and task.exception():
            exc = task.exception()
            return error(exc.status, str(exc), exc.kind)
        if not body.get("stream"):
            try:
                result = await task
            except BridgeError as exc:
                return error(exc.status, str(exc), exc.kind)
            return web.json_response(completion_payload(result, model))
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(request)
        while True:
            try:
                result = await asyncio.wait_for(asyncio.shield(task), 10)
                break
            except asyncio.TimeoutError:
                await response.write(b": waiting for chatgpt.com\n\n")
            except BridgeError as exc:
                payload = {"error": {"message": str(exc), "type": exc.kind, "code": exc.status}}
                await response.write(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode())
                await response.write(b"data: [DONE]\n\n")
                return response
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        for chunk in stream_chunks(result, model, include_usage):
            await response.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
        await response.write(b"data: [DONE]\n\n")
        return response

    app = web.Application(middlewares=[auth], client_max_size=16 * 1024 * 1024)
    app.add_routes([web.get("/health", health), web.get("/v1/models", models),
                    web.post("/v1/chat/completions", chat)])
    return app


async def main():
    from aiohttp import web
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api_key = os.environ.get("CHATGPT_WEB_API_KEY", "")
    if len(api_key) < 24:
        raise SystemExit("CHATGPT_WEB_API_KEY must be set (24+ characters).")
    notifier = Notifier(os.environ.get("HA_URL", ""), os.environ.get("HA_TOKEN", ""))
    browser = Browser(os.environ.get("CHATGPT_WEB_PROFILE", "/data/profile"),
                      int(os.environ.get("CHATGPT_WEB_MAX_TABS", "3")),
                      float(os.environ.get("CHATGPT_WEB_REPLY_TIMEOUT", "300")),
                      os.environ.get("CHATGPT_WEB_TEMPORARY", "1") == "1",
                      os.environ.get("CHATGPT_WEB_MODEL_SLUG", ""), notifier)
    await browser.start()
    asyncio.create_task(browser.monitor())
    runner = web.AppRunner(make_app(browser, api_key))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("CHATGPT_WEB_PORT", "8787"))).start()
    log.info("listening; state=%s", browser.state)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
