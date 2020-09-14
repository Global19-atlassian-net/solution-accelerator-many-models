# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import argparse
from azureml.core import Workspace, Dataset, Environment
from azureml.core.compute import AmlCompute
from azureml.pipeline.core import Pipeline, PipelineData, PublishedPipeline
from azureml.contrib.pipeline.steps import ParallelRunConfig, ParallelRunStep


def main(ws, pipeline_name, pipeline_version, dataset_name, compute_name):

    # Get input dataset
    dataset = Dataset.get_by_name(ws, name=dataset_name)
    dataset_input = dataset.as_named_input(dataset_name)

    # Set output
    datastore = ws.get_default_datastore()
    output_dir = PipelineData(name='training_output', datastore=datastore)

    # Set up ParallelRunStep
    parallel_run_config = get_parallel_run_config(ws, dataset_name, compute_name)
    parallel_run_step = ParallelRunStep(
        name='many-models-parallel-training',
        parallel_run_config=parallel_run_config,
        inputs=[dataset_input],
        output=output_dir,
        allow_reuse=False,
        arguments=[
            '--id_columns', 'Store', 'Brand',
            '--target_column', 'Quantity', 
            '--timestamp_column', 'WeekStarting',
            '--drop_columns', 'Revenue', 'Store', 'Brand',
            '--model_type', 'lr',
            '--test_size', 20
        ]
    )

    # Create the pipeline
    train_pipeline = Pipeline(workspace=ws, steps=[parallel_run_step])
    train_pipeline.validate()

    # Publish it and replace old pipeline
    disable_old_pipelines(ws, pipeline_name)
    published_pipeline = train_pipeline.publish(
        name=pipeline_name,
        description="Many Models training/retraining pipeline",
        version=pipeline_version,
        continue_on_step_failure=False
    )

    return published_pipeline.id


def get_parallel_run_config(ws, dataset_name, compute_name, processes_per_node=8, node_count=3, timeout=300):

    # Configure environment for ParallelRunStep
    train_env = Environment.from_conda_specification(
        name='many_models_environment',
        file_path='Custom_Script/scripts/train.conda.yml'
    )

    # Get the compute target
    compute = AmlCompute(ws, compute_name)

    # Set up ParallelRunStep configuration
    parallel_run_config = ParallelRunConfig(
        source_directory='Custom_Script/scripts/',
        entry_script='train.py',
        mini_batch_size='1',
        run_invocation_timeout=timeout,
        error_threshold=-1,
        output_action='append_row',
        environment=train_env,
        process_count_per_node=processes_per_node,
        compute_target=compute,
        node_count=node_count
    )

    return parallel_run_config


def disable_old_pipelines(ws, pipeline_name):
    for pipeline in PublishedPipeline.list(ws):
        if pipeline.name == pipeline_name:
            pipeline.disable()


def parse_args(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--subscription-id', required=True, type=str)
    parser.add_argument('--resource-group', required=True, type=str)
    parser.add_argument('--workspace-name', required=True, type=str)
    parser.add_argument('--name', required=True, type=str)
    parser.add_argument('--version', required=True, type=str)
    parser.add_argument('--dataset', type=str, default='oj_sales_data')
    parser.add_argument('--compute', type=str, default='cpu-compute')
    args_parsed = parser.parse_args(args)
    return args_parsed


if __name__ == "__main__":
    args = parse_args()

    # Connect to workspace
    ws = Workspace.get(
        name=args.workspace_name,
        subscription_id=args.subscription_id,
        resource_group=args.resource_group
    )

    pipeline_id = main(
        ws,
        pipeline_name=args.name,
        pipeline_version=args.version,
        dataset_name=args.dataset,
        compute_name=args.compute
    )

    print('Training pipeline {} version {} published with ID {}'.format(args.name, args.version, pipeline_id))
