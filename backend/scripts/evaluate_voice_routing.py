"""Native MLflow regression evaluation using synthetic addressed commands only.

Install the optional tracing dependencies. No model, meeting, or account calls.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import mlflow
from mlflow.genai.datasets import create_dataset, search_datasets
from mlflow.genai.scorers import scorer, list_scorers

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bot'))
import meeting_session


@mlflow.trace(name='meeting.voice.route')
def route(command):
    async def run():
        # Evaluate the actual dispatcher without opening a browser or session.
        session = meeting_session.MeetingSession.__new__(meeting_session.MeetingSession)
        session.capture_request_id = 'synthetic'
        session._board_active = True
        selected = {}
        async def submit(page, request, tool): selected.update(tool=tool, command=request.question)
        session.submit_agent_command = submit
        await session.execute_command(None, meeting_session.Command('', command))
        return selected
    return asyncio.run(run())


@scorer
def correct_command_route(outputs, expectations):
    return outputs.get('tool') == expectations['tool']


def main(args):
    if not os.environ.get('MLFLOW_TRACKING_URI'):
        mlflow.set_tracking_uri('sqlite:////private/tmp/wilco-voice-routing.sqlite')
        # This process owns the local SQLite store and the scorer source.
        os.environ.setdefault('MLFLOW_SERVER_ENABLE_CUSTOM_SCORERS', 'true')
    if os.environ.get('MLFLOW_EXPERIMENT_ID'):
        experiment = mlflow.get_experiment(os.environ['MLFLOW_EXPERIMENT_ID'])
        mlflow.set_experiment(experiment_id=experiment.experiment_id)
    else:
        name = 'wilco-voice-routing'
        experiment = mlflow.get_experiment_by_name(name)
        if experiment is None:
            identifier = mlflow.create_experiment(name, artifact_location='/private/tmp/wilco-voice-evaluation-artifacts')
            experiment = mlflow.get_experiment(identifier)
        mlflow.set_experiment(experiment_id=experiment.experiment_id)
    # Verify an actual persisted route trace before starting evaluation.
    route('Open a whiteboard and draw signup, payment and activation')
    trace_id = mlflow.get_last_active_trace_id()
    mlflow.flush_trace_async_logging()
    trace = mlflow.get_trace(trace_id)
    assert trace is not None and trace.data.spans
    print('Verified persisted routing trace:', trace_id)
    datasets = search_datasets(experiment_ids=[experiment.experiment_id])
    print('Existing evaluation datasets:', [dataset.name for dataset in datasets])
    dataset = next((dataset for dataset in datasets if dataset.name == 'voice-command-regressions'), None)
    if dataset is None:
        dataset = create_dataset(name='voice-command-regressions', experiment_id=[experiment.experiment_id])
    cases = [
        ('Open a whiteboard', 'open_board'),
        ('Open Fig Jam', 'open_board'),
        ('Please just open up FigJam', 'open_board'),
        ('I need you to open Jam boards', 'open_board'),
        ('Launch FigJam', 'open_board'),
        ('Open Fig Jam and create a signup flow', 'edit_board'),
        ('Open a whiteboard and draw signup, payment and activation', 'edit_board'),
        ('Open and present a whiteboard with an onboarding flow', 'edit_board'),
        ('Would you please create a FigJam board with a signup flow', 'edit_board'),
        ('Draw signup and verification', 'edit_board'),
        ('Rename signup to create account', 'edit_board'),
        ('Undo that', 'edit_board'),
        ('Add task: Ravi to review the board by Friday', 'add_task'),
        ('Draw the flow and add a task for Ravi to review it', 'auto'),
        ('What have we decided so far?', 'answer'),
    ]
    dataset.merge_records([{'inputs':{'command':command}, 'expectations':{'tool':tool}} for command,tool in cases])
    registered = list_scorers(experiment_id=experiment.experiment_id)
    if not any(item.name == correct_command_route.name for item in registered):
        correct_command_route.register(experiment_id=experiment.experiment_id)
    registered = list_scorers(experiment_id=experiment.experiment_id)
    result = mlflow.genai.evaluate(data=dataset, predict_fn=route, scorers=registered)
    report = {'run_id':result.run_id,'dataset_id':dataset.dataset_id,'synthetic_cases':len(cases),
              'verified_trace_id':trace_id,'metrics':result.metrics,
              'limits':'Routing only; no claim about model accuracy, actual audio, or live FigJam reception.'}
    Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
    assert result.metrics['correct_command_route/mean'] == 1.0
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='/private/tmp/wilco-voice-routing-evaluation.json')
    main(parser.parse_args())
