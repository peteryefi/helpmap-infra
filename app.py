#!/usr/bin/env python3
import os

import aws_cdk as cdk

from helpmap_infra.config import get_config
from helpmap_infra.stacks.testbed_api_stack import TestbedApiStack
from helpmap_infra.stacks.amplify_pwa_stack import AmplifyPwaStack

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

# The testbed PWA's Amplify hosting -- CfnApp/Branch/Domain, defined in
# stacks/amplify_stack.py. Same config object and environment binding as
# the API stack above, so both stacks always deploy against the same
# account/region for a given `-c env=...`.
AmplifyPwaStack(
    app,
    f"Helpmap-{env_name}-Pwa",
    config=config,
    env=aws_env,
)

# Renders the construct tree above into CloudFormation templates.
app.synth()
