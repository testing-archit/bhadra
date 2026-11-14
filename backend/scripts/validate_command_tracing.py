"""Verify stored command traces with synthetic callbacks; no meeting/provider calls.

Run with the optional bot tracing dependencies installed:
    python backend/scripts/validate_command_tracing.py --tracking-uri file:///tmp/wilco-traces
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
from command_runtime import Command, CommandRuntime, stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-uri", required=True)
    parser.add_argument("--experiment-name", default="wilco-command-runtime-smoke")
    args = parser.parse_args()
    os.environ["MEETING_COMMAND_MLFLOW"] = "1"
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"] = "false"
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    import mlflow
    mlflow.set_tracking_uri(args.tracking_uri)
    experiment = mlflow.set_experiment(args.experiment_name)
    commands = [Command("", "synthetic input") for _ in range(2)]
    command_ids = {command.id for command in commands}

    async def scenario():
        async def discover():
            result = commands[:]
            commands.clear()
            return result

        async def execute(command):
            with stage("synthetic-session", command.id, "answer_request"):
                await asyncio.sleep(0)
            return "synthetic output"

        async def play(_reply):
            await asyncio.sleep(0)

        async with CommandRuntime("synthetic-session", discover, execute, play) as runtime:
            # Let intake enqueue before waiting for queues to drain.
            while commands:
                await asyncio.sleep(0)
            await runtime.commands.join()
            await runtime.speech.join()

    asyncio.run(scenario())
    traces = mlflow.search_traces(experiment_ids=[experiment.experiment_id], return_type="list")
    matching = [trace for trace in traces if any(
        span.attributes.get("command_id") in command_ids for span in trace.data.spans
    )]
    assert len(matching) == 4, f"Expected 4 execution/playback traces, found {len(matching)}"
    for trace in matching:
        assert mlflow.get_trace(trace.info.trace_id) is not None
    print(f"Verified {len(matching)} stored and retrievable traces for 2 synthetic commands.")


if __name__ == "__main__":
    main()
