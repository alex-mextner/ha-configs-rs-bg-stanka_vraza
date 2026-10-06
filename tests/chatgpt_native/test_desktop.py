"""Desktop panel registration and shared authorization boundaries."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession, WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from .test_access import make_hass, module


async def test_desktop_preserves_chatgpt_panel(monkeypatch) -> None:
    hass = SimpleNamespace(
        http=SimpleNamespace(
            register_view=lambda _view: None, async_register_static_paths=AsyncMock()
        )
    )
    monkeypatch.setattr(module, "async_get_clientsession", lambda _hass: None)
    register = AsyncMock()
    monkeypatch.setattr(module.panel_custom, "async_register_panel", register)
    await module.async_setup(hass, {})
    panels = [call.kwargs for call in register.await_args_list]
    if {p["frontend_url_path"] for p in panels} != {"chatgpt-native", "ubuntu-desktop"}:
        pytest.fail(
            "Check failed: {p['frontend_url_path'] for p in panels} == {'chatgpt-native', 'ubuntu-desktop'}"
        )
    if not all(p["require_admin"] for p in panels):
        pytest.fail("Check failed: all((p['require_admin'] for p in panels))")
    if {p["module_url"] for p in panels} != {"/chatgpt-native-panel.js"}:
        pytest.fail(
            "Check failed: {p['module_url'] for p in panels} == {'/chatgpt-native-panel.js'}"
        )


async def test_session_cannot_be_bound_to_another_user() -> None:
    hass, session, _ = make_hass()
    request = make_mocked_request("POST", module.BASE + "/session")
    request["hass_user"] = SimpleNamespace(id="other")
    request.json = AsyncMock(return_value={"session": session})
    with pytest.raises(web.HTTPForbidden):
        await module.SessionView(hass).post(request)


async def test_session_cookie_is_scoped_http_only_and_strict() -> None:
    hass, session, admin = make_hass()
    request = make_mocked_request("POST", module.BASE + "/session")
    request["hass_user"] = admin
    request.json = AsyncMock(return_value={"session": session})
    response = await module.SessionView(hass).post(request)
    cookie = response.cookies[module.COOKIE]
    if not cookie["httponly"]:
        pytest.fail("Check failed: cookie['httponly']")
    if cookie["samesite"] != "Strict":
        pytest.fail("Check failed: cookie['samesite'] == 'Strict'")
    if cookie["path"] != module.BASE:
        pytest.fail("Check failed: cookie['path'] == module.BASE")
    if cookie["max-age"] != "300":
        pytest.fail("Check failed: cookie['max-age'] == '300'")


@pytest.mark.parametrize("path", ["vnc.html", "websockify"])
@pytest.mark.parametrize("kind", ["missing", "expired", "nonadmin", "inactive"])
async def test_assets_and_ws_reject_before_upstream(monkeypatch, path, kind) -> None:
    hass, session, admin = make_hass()
    upstream = SimpleNamespace(get=AsyncMock(), ws_connect=AsyncMock())
    monkeypatch.setattr(module, "async_get_clientsession", lambda _hass: upstream)
    view = module.GUIView(hass)
    if kind == "nonadmin":
        admin.is_admin = False
    if kind == "inactive":
        admin.is_active = False
    headers = (
        {}
        if kind == "missing"
        else {
            "Cookie": f"{module.COOKIE}={('expired' if kind == 'expired' else session)}"
        }
    )
    request = make_mocked_request("GET", module.BASE + "/" + path, headers=headers)
    with pytest.raises(
        web.HTTPUnauthorized if kind in {"missing", "expired"} else web.HTTPForbidden
    ):
        await view.get(request, path)
    upstream.get.assert_not_called()
    upstream.ws_connect.assert_not_called()


@pytest.mark.parametrize("path", ["../vnc.html", "/vnc.html", "app/../vnc.html"])
async def test_traversal_is_rejected(monkeypatch, path) -> None:
    hass, session, _ = make_hass()
    monkeypatch.setattr(module, "async_get_clientsession", lambda _hass: None)
    request = make_mocked_request(
        "GET",
        module.BASE + "/" + path,
        headers={"Cookie": f"{module.COOKIE}={session}"},
    )
    with pytest.raises(web.HTTPBadRequest):
        await module.GUIView(hass).get(request, path)


async def test_live_websocket_closes_when_role_is_revoked(monkeypatch) -> None:
    """Exercise actual binary relay and the existing periodic permission recheck."""
    hass, session, admin = make_hass()

    async def echo(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(protocols=["binary"])
        await ws.prepare(request)
        async for message in ws:
            if message.type == WSMsgType.BINARY:
                await ws.send_bytes(message.data)
        return ws

    backend = web.Application()
    backend.router.add_get("/websockify", echo)
    async with TestServer(backend) as server, ClientSession() as upstream:
        monkeypatch.setattr(module, "BACKEND", str(server.make_url("/")).rstrip("/"))
        monkeypatch.setattr(module, "async_get_clientsession", lambda _hass: upstream)
        original_sleep = asyncio.sleep

        async def accelerated_recheck(delay: float) -> None:
            await original_sleep(0.02 if delay == 30 else delay)

        monkeypatch.setattr(module.asyncio, "sleep", accelerated_recheck)
        view = module.GUIView(hass)
        app = web.Application()

        async def proxy(request: web.Request) -> web.StreamResponse:
            return await view.get(request, "websockify")

        app.router.add_get("/websockify", proxy)
        async with (
            TestClient(TestServer(app)) as client,
            client.ws_connect(
                "/websockify",
                protocols=["binary"],
                headers={"Cookie": f"{module.COOKIE}={session}"},
            ) as ws,
        ):
            await ws.send_bytes(b"desktop-frame")
            if (await ws.receive(timeout=1)).data != b"desktop-frame":
                pytest.fail(
                    "Check failed: (await ws.receive(timeout=1)).data == b'desktop-frame'"
                )
            admin.is_admin = False
            if (await ws.receive(timeout=1)).type != WSMsgType.CLOSE:
                pytest.fail(
                    "Check failed: (await ws.receive(timeout=1)).type == WSMsgType.CLOSE"
                )


@pytest.mark.parametrize("peer", ["127.0.0.1", "172.20.0.6", "192.168.0.39"])
async def test_bridge_rejects_non_ha_peer_even_with_forwarded_header(
    monkeypatch, peer
) -> None:
    monkeypatch.setattr(web, "run_app", lambda *_args, **_kwargs: None)
    spec = importlib.util.spec_from_file_location(
        "desktop_bridge", Path(__file__).parents[2] / "scripts/chatgpt_native/bridge.py"
    )
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    request = SimpleNamespace(remote=peer, headers={"X-Forwarded-For": "172.20.0.5"})
    handler = AsyncMock()
    with pytest.raises(web.HTTPForbidden):
        await bridge.private_peer(request, handler)
    handler.assert_not_called()
