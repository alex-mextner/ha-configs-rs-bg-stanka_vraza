#!/usr/bin/env python3
import asyncio, json, os, websockets

TOKEN = os.environ['HA_TOKEN']
ENTRY_ID = '01KS0SK1NAJJAP1SSCDYCKRW4M'
URI = 'ws://localhost:8123/api/websocket'

async def disable():
    async with websockets.connect(URI) as ws:
        msg = json.loads(await ws.recv())
        if msg.get('type') != 'auth_required':
            print('Unexpected:', msg)
            return
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        msg = json.loads(await ws.recv())
        if msg.get('type') != 'auth_ok':
            print('Auth failed:', msg)
            return
        await ws.send(json.dumps({
            "id": 1,
            "type": "config_entries/update",
            "entry_id": ENTRY_ID,
            "disabled_by": "user"
        }))
        msg = json.loads(await ws.recv())
        print(json.dumps(msg, indent=2, ensure_ascii=False))

asyncio.run(disable())
