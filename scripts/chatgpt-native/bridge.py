import asyncio
from pathlib import Path
from aiohttp import web, WSMsgType

ROOT = Path('/home/ultra/.local/share/chatgpt-native-ha/gui-runtime/root/usr/share/novnc')

@web.middleware
async def private_peer(request, handler):
    if request.remote != '172.20.0.5':
        raise web.HTTPForbidden()
    return await handler(request)

async def websocket(request):
    ws = web.WebSocketResponse(protocols=['binary'])
    await ws.prepare(request)
    reader, writer = await asyncio.open_connection('127.0.0.1', 5901)
    async def incoming():
        async for message in ws:
            if message.type == WSMsgType.BINARY:
                writer.write(message.data)
                await writer.drain()
    async def outgoing():
        while data := await reader.read(65536):
            await ws.send_bytes(data)
    tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        await writer.wait_closed()
        await ws.close()
    return ws

app = web.Application(middlewares=[private_peer])
app.router.add_get('/websockify', websocket)
app.router.add_static('/', ROOT)
web.run_app(app, host='172.20.0.1', port=6081, print=None)
