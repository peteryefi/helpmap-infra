"""
Contributors:
    Peter Yefi - API design and implementation
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EnvironmentConfig:
    env_name: str
    account: Optional[str]
    region: str
    api_domain_name: str
    pwa_domain_name: str
    admin_cidr: str
    lightsail_bundle_id: str
    lightsail_blueprint_id: str
    pwa_repository_url: str
    pwa_branch_name: str
    root_domain: str
    github_token_secret_name: str
    mapbox_token_secret_name: str
    restrict_reports_by_area: bool
    use_fake_user_location: bool
    pwa_monorepo_app_root: str
    map_style_url: Optional[str] = None



_CONFIGS = {
    "testbed": EnvironmentConfig(
        env_name="testbed",
        account=None,
        region="us-west-2",
        api_domain_name="api-testbed.helpmap.us",
        pwa_domain_name="testbed.helpmap.us",
        admin_cidr="24.225.231.56/32",
        lightsail_bundle_id="nano_3_0",
        lightsail_blueprint_id="ubuntu_24_04",
        pwa_repository_url="https://github.com/Helpmap-Agency/helpmap-LACounty",
        pwa_monorepo_app_root="app",
        pwa_branch_name="testbed",
        root_domain="helpmap.us",
        github_token_secret_name="helpmap/github-token",
        mapbox_token_secret_name="helpmap/mapbox-token",
        restrict_reports_by_area=False,
        use_fake_user_location=False,
        map_style_url=None,
    ),
}


def get_config(env_name: str) -> EnvironmentConfig:
    try:
        return _CONFIGS[env_name]
    except KeyError:
        raise ValueError(
            f"Unknown environment '{env_name}'. Known environments: {sorted(_CONFIGS)}"
        )
