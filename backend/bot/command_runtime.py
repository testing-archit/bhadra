"""Bounded per-meeting command execution, independent of capture/lifecycle checks."""
import asyncio
import logging
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field

log = logging.getLogger("command_runtime")


@dataclass
class Command:
    asked: str
    question: str
    received_at: float = field(default_factory=time.monotonic)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    follow_up: str | None = None


@contextmanager
def stage(session_id: str, command_id: str, name: str, **attributes):
    """Metadata-only timings always work; MLflow export is explicitly opt-in.

    No transcript, speaker, question, reply, or provider exception text is exported.
    Configure MLflow in the process environment before enabling export.
    """
    import os
    import json

    started = time.monotonic()
    status = "ok"
    exporter = None
    span = None
    if os.environ.get("MEETING_COMMAND_MLFLOW") == "1":
        try:
            import mlflow
            exporter = mlflow.start_span(
                name=f"meeting.command.{name}",
                attributes={"session_id": session_id, "command_id": command_id, **attributes},
            )
            span = exporter.__enter__()
        except Exception:
            exporter = None
            log.warning("Command trace export unavailable")
    try:
        yield
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception:
        status = "error"
        raise
    finally:
        log.info("command_timing %s", json.dumps({
            "session_id": session_id, "command_id": command_id,
            "stage": name, "status": status,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            **attributes,
        }))
        if exporter is not None:
            try:
                span.set_attribute("outcome", status)
            except Exception:
                log.warning("Command trace attribute unavailable")
            finally:
                try:
                    # Never forward provider exceptions: they may contain private
                    # request/response bodies. The outcome attribute records failure.
                    exporter.__exit__(None, None, None)
                except Exception:
                    log.warning("Command trace export unavailable")


class CommandRuntime:
    """One execution worker and one playback worker; bounded backpressure.

    Cancellation discards queued work and output. It cannot undo an HTTP write
    already executing inside a synchronous uploader thread.
    """
    def __init__(self, session_id, discover, execute, play, *, capacity=8, poll_seconds=0.5, control=None, busy=None, speech_max_age=10):
        self.session_id = session_id
        self.control = control
        self.busy = busy
        self.speech_max_age = speech_max_age
        self._playing = None
        self._closing = False
        self._speech_epoch = 0
        self._work_epoch = 0
        self._work_task = None
        self._executing_command = None
        self._backlog = deque()
        self.discover = discover
        self.execute = execute
        self.play = play
        self.poll_seconds = poll_seconds
        self.commands = asyncio.Queue(maxsize=capacity)
        self.speech = asyncio.Queue(maxsize=capacity)
        self.changed = asyncio.Event()
        self.tasks = []

    async def __aenter__(self):
        self.tasks = [asyncio.create_task(worker()) for worker in (
            self._intake, self._execute, self._play,
        )]
        return self

    async def __aexit__(self, *_):
        self._closing = True
        await self.interrupt_speech()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self._backlog.clear()
        for queue in (self.commands, self.speech):
            while not queue.empty():
                queue.get_nowait()
                queue.task_done()

    async def interrupt_speech(self):
        self._speech_epoch += 1
        while not self.speech.empty():
            self.speech.get_nowait()
            self.speech.task_done()
        if self._playing is not None:
            self._playing.cancel()
            await asyncio.gather(self._playing, return_exceptions=True)

    async def cancel_latest(self):
        if self._backlog:
            return [self._backlog.pop()]
        queued = []
        while not self.commands.empty():
            queued.append(self.commands.get_nowait())
            self.commands.task_done()
        if queued:
            for command in queued[:-1]:
                self.commands.put_nowait(command)
            return queued[-1:]
        if self._work_task is not None:
            command = self._executing_command
            self._work_epoch += 1
            self._work_task.cancel()
            await asyncio.gather(self._work_task, return_exceptions=True)
            return [command] if command else []
        return []

    async def cancel_all(self):
        commands = list(self._backlog)
        self._backlog.clear()
        while not self.commands.empty():
            commands.append(self.commands.get_nowait())
            self.commands.task_done()
        commands.extend(await self.cancel_latest())
        return commands

    async def enqueue_reply(self, command, reply):
        await self.speech.put((command, reply, time.monotonic()))

    async def _intake(self):
        pending = self._backlog
        while True:
            self.changed.clear()
            try:
                for command in await self.discover():
                    if self.control and await self.control(command):
                        continue
                    if len(pending) < 32:
                        pending.append(command)
                    elif self.busy:
                        await self.busy(command)
                    else:
                        log.warning("Command admission full; rejected %s", command.id)
                while pending and not self.commands.full():
                    self.commands.put_nowait(pending.popleft())
            except Exception as error:
                log.warning("Command intake failed (%s)", type(error).__name__)
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    async def _execute(self):
        while True:
            command = await self.commands.get()
            self.changed.set()
            try:
                with stage(self.session_id, command.id, "execute",
                           queue_ms=round((time.monotonic() - command.received_at) * 1000, 2)):
                    epoch = self._work_epoch
                    self._executing_command = command
                    self._work_task = asyncio.create_task(self.execute(command))
                    try:
                        reply = await self._work_task
                    except asyncio.CancelledError:
                        if self._closing or epoch == self._work_epoch:
                            raise
                        reply = None
                    finally:
                        self._work_task = None
                        self._executing_command = None
                if reply:
                    await self.enqueue_reply(command, reply)
            except Exception as error:
                log.warning("Command execution failed (%s)", type(error).__name__)
            finally:
                self.commands.task_done()

    async def _play(self):
        while True:
            command, reply, queued_at = await self.speech.get()
            try:
                with stage(self.session_id, command.id, "speech",
                           queue_ms=round((time.monotonic() - queued_at) * 1000, 2)):
                    if time.monotonic() - queued_at > self.speech_max_age:
                        log.info("Skipped stale speech for command %s", command.id)
                        continue
                    epoch = self._speech_epoch
                    self._playing = asyncio.create_task(self.play(reply))
                    try:
                        await self._playing
                    except asyncio.CancelledError:
                        if self._closing or epoch == self._speech_epoch:
                            raise
                    finally:
                        self._playing = None
            except Exception as error:
                log.warning("Command playback failed (%s)", type(error).__name__)
            finally:
                self.speech.task_done()
