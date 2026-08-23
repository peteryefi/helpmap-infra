"""
Contributors:
    Peter Yefi - API design and implementation
"""
from constructs import Construct
from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_lightsail as lightsail

from helpmap_infra.config import EnvironmentConfig


class TestbedApiStack(Stack):
    """Lightsail instance + static IP + firewall for the reports API."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        instance_name = f"helpmap-{config.env_name}-api-v2"

        instance = lightsail.CfnInstance(
            self,
            "ApiInstanceV2",
            instance_name=instance_name,
            # Lightsail requires a specific AZ, not just a region. This
            # assumes the region's first AZ exists (true for us-west-2).
            # Use `aws lightsail get-regions --include-availability-zones` to confirm.
            availability_zone=f"{config.region}a",
            blueprint_id=config.lightsail_blueprint_id,
            bundle_id=config.lightsail_bundle_id,
            networking=lightsail.CfnInstance.NetworkingProperty(
                ports=[
                    lightsail.CfnInstance.PortProperty(
                        from_port=22,
                        to_port=22,
                        protocol="tcp",
                        cidrs=[config.admin_cidr],
                        common_name="SSH",
                    ),
                    lightsail.CfnInstance.PortProperty(
                        from_port=80,
                        to_port=80,
                        protocol="tcp",
                        cidrs=["0.0.0.0/0"],
                        common_name="HTTP",
                    ),
                    lightsail.CfnInstance.PortProperty(
                        from_port=443,
                        to_port=443,
                        protocol="tcp",
                        cidrs=["0.0.0.0/0"],
                        common_name="HTTPS",
                    ),
                ],
            ),
        )

        static_ip = lightsail.CfnStaticIp(
            self,
            "ApiStaticIp",
            static_ip_name=f"helpmap-{config.env_name}-api-ip",
            attached_to=instance_name,
        )
        # This is to force CDK to create the instance before the static IP
        static_ip.add_resource_dependency(instance)

        CfnOutput(
            self,
            "ApiStaticIpAddress",
            value=static_ip.attr_ip_address,
            description=f"Point {config.api_domain_name} (A record, at GoDaddy) at this IP.",
        )