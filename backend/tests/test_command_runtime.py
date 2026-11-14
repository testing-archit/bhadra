"""Scheduling regressions: no provider, browser, credentials or database needed."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
from command_runtime import Command, CommandRuntime, stage
sys.path.pop(0)


def test_slow_playback_does_not_block_execution_or_intake():
    async def scenario():
        incoming = [Command("", "first"), Command("", "second")]
        executed = []
        playing = asyncio.Event()
        both_done = asyncio.Event()
        release_audio = asyncio.Event()

        async def discover():
            result = incoming[:]
            incoming.clear()
            return result

        async def execute(command):
            executed.append(command.question)
            if len(executed) == 2:
                both_done.set()
            return command.question

        async def play(_reply):
            playing.set()
            await release_audio.wait()

        async with CommandRuntime("session", discover, execute, play) as runtime:
            await asyncio.wait_for(playing.wait(), 1)
            await asyncio.wait_for(both_done.wait(), 1)
            assert executed == ["first", "second"]
        assert all(task.done() for task in runtime.tasks)
        assert runtime.speech.empty()
    asyncio.run(scenario())


def test_backpressure_retains_every_discovered_command_and_recovers_from_error():
    async def scenario():
        incoming = [Command("", str(n)) for n in range(12)]
        seen = []
        done = asyncio.Event()

        async def discover():
            result = incoming[:]
            incoming.clear()
            return result

        async def execute(command):
            seen.append(command.question)
            if command.question == "0":
                raise RuntimeError("provider unavailable")
            if len(seen) == 12:
                done.set()
            return command.question

        async def play(_reply):
            await asyncio.sleep(0)

        async with CommandRuntime("s", discover, execute, play, capacity=1):
            await asyncio.wait_for(done.wait(), 1)
        assert seen == [str(n) for n in range(12)]
    asyncio.run(scenario())


def test_caption_event_wakes_intake_before_chat_poll_timeout():
    async def scenario():
        incoming = []
        initial = asyncio.Event()
        done = asyncio.Event()

        async def discover():
            initial.set()
            result = incoming[:]
            incoming.clear()
            return result

        async def execute(command):
            done.set()

        async def play(_reply):
            pass

        async with CommandRuntime("s", discover, execute, play, poll_seconds=60) as runtime:
            await asyncio.wait_for(initial.wait(), 1)
            incoming.append(Command("", "new caption"))
            runtime.changed.set()
            await asyncio.wait_for(done.wait(), 1)
    asyncio.run(scenario())


def test_timing_metadata_does_not_contain_command_content(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="command_runtime")
    with stage("session-id", "command-id", "execute", queue_ms=3):
        pass
    assert '"command_id": "command-id"' in caplog.text
    assert '"duration_ms"' in caplog.text
    assert '"status": "ok"' in caplog.text


def test_exporter_failure_cannot_fail_the_command_or_export_exception_text(monkeypatch, caplog):
    import logging
    import types
    caplog.set_level(logging.INFO, logger="command_runtime")
    exits = []

    class Export:
        def __enter__(self):
            return self

        def set_attribute(self, *_args):
            pass

        def __exit__(self, *args):
            exits.append(args)
            raise RuntimeError("export unavailable")

    monkeypatch.setenv("MEETING_COMMAND_MLFLOW", "1")
    monkeypatch.setitem(sys.modules, "mlflow", types.SimpleNamespace(start_span=lambda **_kw: Export()))
    import pytest
    with pytest.raises(ValueError, match="private body"):
        with stage("s", "c", "execute"):
            raise ValueError("private body")
    assert exits == [(None, None, None)]
    assert "private body" not in caplog.text
    assert '"status": "error"' in caplog.text
    with stage("s", "c", "execute"):
        pass
