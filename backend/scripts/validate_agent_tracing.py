"""Verify native MLflow storage for content-free backend agent spans; no inference."""
import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.agent_telemetry import stage


def main(args):
    os.environ['MEETING_AGENT_MLFLOW']='1'
    os.environ['MLFLOW_ENABLE_ASYNC_TRACE_LOGGING']='false'
    os.environ['MLFLOW_ALLOW_FILE_STORE']='true'
    import mlflow
    mlflow.set_tracking_uri(args.tracking_uri)
    experiment=mlflow.set_experiment('wilco-durable-agent-trace-smoke')
    identifiers={str(uuid.uuid4()) for _ in range(2)}
    for identifier in identifiers:
        with stage(identifier,'run',attempt=1):
            with stage(identifier,'plan'):
                pass
            with stage(identifier,'tool',tool='open_board'):
                pass
    traces=mlflow.search_traces(experiment_ids=[experiment.experiment_id],return_type='list')
    matching=[trace for trace in traces if any(span.attributes.get('job_id') in identifiers for span in trace.data.spans)]
    assert len(matching)==2
    assert all(len(trace.data.spans)==3 for trace in matching)
    assert all(mlflow.get_trace(trace.info.trace_id) is not None for trace in matching)
    print('Verified 2 stored/retrievable agent traces, each with run, plan and tool spans.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tracking-uri',required=True)
    main(parser.parse_args())
