import asyncio
from typing import Any

import py_eureka_client.eureka_client as eureka_client


class Discovery:
    def __init__(
        self,
        app_name,
        service_url,
        service_port,
        service_user,
        service_password,
        instance_ip,
        instance_host,
        instance_port,
        **kwargs: Any,
    ):
        self.app_name = app_name
        self.service_url = service_url
        self.service_port = service_port
        self.service_user = service_user
        self.service_password = service_password
        self.instance_ip = instance_ip
        self.instance_host = instance_host
        self.instance_port = instance_port

    def register(self):
        eureka_client.init(
            eureka_server=self.service_url,
            app_name=self.app_name,
            instance_port=self.service_port,
            eureka_basic_auth_user=self.service_user,
            eureka_basic_auth_password=self.service_password,
        )

    def unregister(self):
        eureka_client.stop()

    async def register_async(self):
        asyncio.create_task(
            eureka_client.init_async(
                eureka_server=self.service_url,
                app_name=self.app_name,
                eureka_basic_auth_user=self.service_user,
                eureka_basic_auth_password=self.service_password,
                instance_ip=self.instance_ip,
                instance_host=self.instance_host,
                instance_port=self.instance_port,
            )
        )

    async def unregister_async(self):
        await eureka_client.stop_async()

    def __str__(self):
        return (
            f"Discovery(app_name={self.app_name}, "
            f"service_url={self.service_url}, "
            f"instance_host={self.instance_host}, "
            f"instance_port={self.instance_port})"
        )
