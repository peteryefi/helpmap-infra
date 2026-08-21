#!/usr/bin/env python3
import os

import aws_cdk as cdk

from helpmap_infra.config import get_config
from helpmap_infra.stacks.testbed_api_stack import TestbedApiStack

app = cdk.App()

# Which environment are we building? Defaults to testbed if not passed
# via `cdk deploy -c env=production`.
env_name = app.node.try_get_context("env") or "testbed"
config = get_config(env_name)

# Pin to a specific AWS account/region if config says so (e.g. production);
# otherwise fall back to whatever account/region the CLI is currently
# authenticated against.
aws_env = cdk.Environment(
    account=config.account or os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=config.region or os.getenv("CDK_DEFAULT_REGION"),
)

# The testbed's reports API infrastructure (Lightsail instance, static IP,
# firewall) -- defined in stacks/testbed_api_stack.py.
TestbedApiStack(
    app,
    f"Helpmap-{env_name}-Api",
    config=config,
    env=aws_env,
)

# Renders the construct tree above into CloudFormation templates.
app.synth()
