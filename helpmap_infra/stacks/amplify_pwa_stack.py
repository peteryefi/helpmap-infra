"""
Contributors:
    Peter Yefi - API design and implementation
"""
from aws_cdk import (
    Stack,
    CfnOutput,
    aws_amplify as amplify,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct
from pathlib import Path

from helpmap_infra.config import EnvironmentConfig

BUILD_SPEC_PATH = Path(__file__).parent / "buildspecs" / "pwa.buildspec.yml"


class AmplifyPwaStack(Stack):
    """Hosts the Helpmap PWA on AWS Amplify, built from the Next.js app
    living at `config.pwa_monorepo_app_root` inside the GitHub repo."""

    def __init__(self, scope: Construct, construct_id: str, config: EnvironmentConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Secrets: referenced by name only, resolved by CloudFormation
        # at deploy time.
        github_token = secretsmanager.Secret.from_secret_name_v2(
            self, "GitHubTokenSecret", config.github_token_secret_name
        )
        mapbox_token = secretsmanager.Secret.from_secret_name_v2(
            self, "MapboxTokenSecret", config.mapbox_token_secret_name
        )

        # --- Build spec: this is a monorepo, so Amplify needs to be told
        # the Next.js project actually lives in the `app/` subdirectory,
        # not the repo root.
        build_spec = BUILD_SPEC_PATH.read_text().format(app_root=config.pwa_monorepo_app_root)

        app = amplify.CfnApp(
            self, "PwaApp",
            name="helpmap-pwa-testbed",
            repository=config.pwa_repository_url,
            access_token=github_token.secret_value.unsafe_unwrap(),
            platform="WEB_COMPUTE",
            build_spec=build_spec,
            environment_variables=[
                amplify.CfnApp.EnvironmentVariableProperty(
                    name="AMPLIFY_MONOREPO_APP_ROOT",
                    value=config.pwa_monorepo_app_root,
                ),
                amplify.CfnApp.EnvironmentVariableProperty(
                    name="NEXT_PUBLIC_API_BASE_URL",
                    value=f"https://{config.api_domain_name}",
                ),
                amplify.CfnApp.EnvironmentVariableProperty(
                    name="NEXT_PUBLIC_MAP_TOKEN",
                    value=mapbox_token.secret_value.unsafe_unwrap(),
                ),
                amplify.CfnApp.EnvironmentVariableProperty(
                    name="NEXT_PUBLIC_RESTRICT_REPORTS_BY_AREA",
                    value=str(config.restrict_reports_by_area).lower(),
                ),
                amplify.CfnApp.EnvironmentVariableProperty(
                    name="NEXT_PUBLIC_USE_FAKE_USER_LOCATION",
                    value=str(config.use_fake_user_location).lower(),
                ),
            ],
        )

        branch = amplify.CfnBranch(
            self, "MainBranch",
            app_id=app.attr_app_id,
            branch_name="main",
            enable_auto_build=True,
            stage="DEVELOPMENT",
        )

        # AWS::Amplify::Domain wants the root/apex domain plus a separate
        # subdomain prefix -- it won't take "testbed.helpmap.us" as one
        # string. `pwa_domain_name` stays a single readable value in
        # config.py; split it here into the two pieces Amplify actually
        # wants.
        prefix, root_domain = config.pwa_domain_name.split(".", 1)

        domain = amplify.CfnDomain(
            self, "PwaDomain",
            app_id=app.attr_app_id,
            domain_name=root_domain,
            sub_domain_settings=[
                amplify.CfnDomain.SubDomainSettingProperty(
                    branch_name=branch.branch_name,
                    prefix=prefix,
                )
            ],
        )
        domain.add_resource_dependency(branch)

        CfnOutput(
            self, "AmplifyDefaultDomain",
            value=app.attr_default_domain,
            description="Amplify's auto-generated URL -- usable immediately, before the custom domain's DNS propagates.",
        )
        CfnOutput(
            self, "PwaCustomDomain",
            value=f"https://{config.pwa_domain_name}",
            description="Custom domain URL -- check the Amplify console's Domain management tab for the CNAME record to add at Squarespace.",
        )
