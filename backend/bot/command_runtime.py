"""Bounded per-meeting command execution, independent of capture/lifecycle checks."""
import asyncio
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

log = logging.getLogger("command_runtime")


@dataclass
class Command:
    asked: str
    question: str
    received_at: float = field(default_factory=time.monotonic)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


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
    def __init__(self, session_id, discover, execute, play, *, capacity=8, poll_seconds=0.5):
        self.session_id = session_id
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
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for queue in (self.commands, self.speech):
            while not queue.empty():
                queue.get_nowait()
                queue.task_done()

    async def _intake(self):
        while True:
            self.changed.clear()
            try:
                for command in await self.discover():
                    # A full queue pauses intake; discovered commands are not dropped.
                    await self.commands.put(command)
            except Exception as error:
                log.warning("Command intake failed (%s)", type(error).__name__)
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    async def _execute(self):
        while True:
            command = await self.commands.get()
            try:
                with stage(self.session_id, command.id, "execute",
                           queue_ms=round((time.monotonic() - command.received_at) * 1000, 2)):
                    reply = await self.execute(command)
                if reply:
                    await self.speech.put((command, reply, time.monotonic()))
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
                    await self.play(reply)
            except Exception as error:
                log.warning("Command playback failed (%s)", type(error).__name__)
            finally:
                self.speech.task_done()
