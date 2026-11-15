"""Persistent asynchronous transport for durable meeting commands."""
import asyncio

import httpx
import config


class AgentClient:
    def __init__(self, capture_id, *, transport=None):
        self.base = f'/api/bot/capture-requests/{capture_id}/commands'
        self.browser_base = f'/api/bot/capture-requests/{capture_id}/browser-actions'
        self.client = httpx.AsyncClient(base_url=config.BACKEND_URL,
            headers={'Authorization': f"Bot {config.require('BOT_API_SECRET')}"},
            timeout=httpx.Timeout(5, connect=2), limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            transport=transport)

    async def close(self):
        await self.client.aclose()

    async def submit(self, command, tool, captions, board_active):
        payload = {'command_id': command.id, 'command': command.question[:1000], 'tool': tool,
                   'captions': compact_captions(captions), 'board_active': board_active,
                   'present_after': command.follow_up == 'present_board' or tool in {'open_board', 'edit_board'}, 'board_provider': 'figjam',
                   'browser_executor': True}
        for attempt in range(2):
            try:
                response = await self.client.post(self.base, json=payload)
                if response.status_code == 429:
                    raise AgentBusy()
                response.raise_for_status()
                return response.json()
            except httpx.TransportError:
                # Retrying with the same command UUID is safe if acceptance was lost.
                if attempt:
                    raise
                await asyncio.sleep(0.1)

    async def outstanding(self):
        response = await self.client.get(self.base)
        response.raise_for_status()
        return response.json()

    async def cancel(self, command_id):
        response = await self.client.post(self.base + f'/{command_id}/cancel')
        response.raise_for_status()
        return response.json()

    async def delivered(self, command_id):
        response = await self.client.post(self.base + f'/{command_id}/delivered')
        response.raise_for_status()

    async def claim_browser(self):
        response = await self.client.post(self.browser_base + '/claim')
        response.raise_for_status()
        return response.json()['action']

    async def check_browser(self, action):
        response = await self.client.post(self.browser_base + f'/{action["id"]}/check',
                                         json={'claim_token': action['claim_token']})
        response.raise_for_status()

    async def complete_browser(self, action, result):
        response = await self.client.post(self.browser_base + f'/{action["id"]}/complete',
                                         json={'claim_token': action['claim_token'], **result})
        response.raise_for_status()


class AgentBusy(Exception):
    pass


def compact_captions(captions, budget=12000):
    selected=[]
    for item in reversed(captions[-120:]):
        value=str(item.get('text') or '')[-min(budget,1500):]
        if not value:
            continue
        selected.append({'speaker': str(item.get('speaker') or '')[:100],
                         'text': value, 'start': max(0, min(28800, float(item.get('start') or 0)))})
        budget-=len(value)
        if budget<=0:
            break
    return selected[::-1]
