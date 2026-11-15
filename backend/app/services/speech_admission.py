"""One Gnani request at a time; live turns go before the next batch chunk."""
import asyncio
from contextlib import asynccontextmanager


class SpeechAdmission:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.active = False
        self.live_waiters = 0

    @asynccontextmanager
    async def slot(self, interactive=False):
        async with self.condition:
            if interactive:
                self.live_waiters += 1
            try:
                await self.condition.wait_for(lambda: not self.active and (interactive or self.live_waiters == 0))
                self.active = True
            finally:
                if interactive:
                    self.live_waiters -= 1
                    self.condition.notify_all()
        try:
            yield
        finally:
            async with self.condition:
                self.active = False
                self.condition.notify_all()
