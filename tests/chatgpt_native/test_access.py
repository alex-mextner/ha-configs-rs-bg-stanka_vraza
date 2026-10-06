"""Authorization regression checks runnable in the installed HA container image."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from aiohttp import web

spec = importlib.util.spec_from_file_location('native', Path(__file__).parents[2] / 'custom_components/chatgpt_native/__init__.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

async def checks():
    store = SimpleNamespace(check_user_token=lambda token: {'id': 'a'} if token == 'valid' else None)
    admin = SimpleNamespace(id='a', is_active=True, is_admin=True)
    auth = SimpleNamespace(async_get_user=AsyncMock(return_value=admin))
    hass = SimpleNamespace(data={'ingress': {'config': store}}, auth=auth)
    assert await module.require_admin(hass, 'valid') is admin
    for token, user, status in [('', admin, 401), ('expired', admin, 401),
                                ('valid', None, 403),
                                ('valid', SimpleNamespace(is_active=False, is_admin=True), 403),
                                ('valid', SimpleNamespace(is_active=True, is_admin=False), 403)]:
        auth.async_get_user.return_value = user
        try:
            await module.require_admin(hass, token)
        except web.HTTPException as error:
            assert error.status == status
        else:
            raise AssertionError('Access was unexpectedly allowed')
    # Previously authorized sessions lose access after current HA role is revoked.
    auth.async_get_user.return_value = admin
    await module.require_admin(hass, 'valid')
    admin.is_admin = False
    try:
        await module.require_admin(hass, 'valid')
    except web.HTTPForbidden:
        pass
    else:
        raise AssertionError('Role revocation ignored')
    print('PASS: administrator, missing/expired session, deleted/inactive/non-admin user, role revocation')

asyncio.run(checks())
