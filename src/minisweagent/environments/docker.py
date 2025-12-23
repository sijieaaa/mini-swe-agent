import logging
import os
import shlex
import subprocess
import uuid
from typing import Any

from pydantic import BaseModel


class DockerEnvironmentConfig(BaseModel):
    image: str | None = None
    """Docker image to use when starting a new container."""
    cwd: str = "/"
    """Working directory in which to execute commands."""
    container_id: str | None = None
    """Use an existing container ID instead of starting a new one."""
    container_name: str | None = None
    """Use an existing container name instead of starting a new one."""
    manage_container: bool | None = None
    """Whether to stop/remove the container on cleanup. Defaults to False for existing containers."""
    env: dict[str, str] = {}
    """Environment variables to set in the container."""
    forward_env: list[str] = []
    """Environment variables to forward to the container.
    Variables are only forwarded if they are set in the host environment.
    In case of conflict with `env`, the `env` variables take precedence.
    """
    timeout: int = 30
    """Timeout for executing commands in the container."""
    executable: str = os.getenv("MSWEA_DOCKER_EXECUTABLE", "docker")
    """Path to the docker/container executable."""
    run_args: list[str] = ["--rm"]
    """Additional arguments to pass to the docker/container executable.
    Default is ["--rm"], which removes the container after it exits.
    """
    container_timeout: str = "2h"
    """Max duration to keep container running. Uses the same format as the sleep command."""
    pull_timeout: int = 120
    """Timeout in seconds for pulling images."""


class DockerEnvironment:
    def __init__(
        self,
        *,
        config_class: type = DockerEnvironmentConfig,
        logger: logging.Logger | None = None,
        **kwargs,
    ):
        """This class executes bash commands in a Docker container using direct docker commands.
        See `DockerEnvironmentConfig` for keyword arguments.
        """
        self.logger = logger or logging.getLogger("minisweagent.environment")
        self.container_id: str | None = None
        self.config = config_class(**kwargs)
        self._manage_container = self.config.manage_container
        if self._manage_container is None:
            self._manage_container = not (self.config.container_id or self.config.container_name)
        if self.config.container_id or self.config.container_name:
            self.container_id = self.config.container_id or self._resolve_container_id(self.config.container_name)
        else:
            self._start_container()

    def get_template_vars(self) -> dict[str, Any]:
        return self.config.model_dump()

    def _start_container(self):
        """Start the Docker container and return the container ID."""
        if not self.config.image:
            raise ValueError("image is required when starting a new container.")
        container_name = f"minisweagent-{uuid.uuid4().hex[:8]}"
        cmd = [
            self.config.executable,
            "run",
            "-d",
            "--name",
            container_name,
            "-w",
            self.config.cwd,
            *self.config.run_args,
            self.config.image,
            "sleep",
            self.config.container_timeout,
        ]
        self.logger.debug(f"Starting container with command: {shlex.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.config.pull_timeout,  # docker pull might take a while
            check=True,
        )
        self.logger.info(f"Started container {container_name} with ID {result.stdout.strip()}")
        self.container_id = result.stdout.strip()

    def _resolve_container_id(self, container_name: str | None) -> str:
        if not container_name:
            raise ValueError("container_name is required to resolve container ID.")
        cmd = [self.config.executable, "inspect", "-f", "{{.Id}}", container_name]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.config.pull_timeout,
            check=True,
        )
        container_id = result.stdout.strip()
        if not container_id:
            raise RuntimeError(f"Could not resolve container ID for {container_name}.")
        cmd = [self.config.executable, "inspect", "-f", "{{.State.Running}}", container_name]
        state = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.config.pull_timeout,
            check=True,
        ).stdout.strip()
        if state.lower() != "true":
            raise RuntimeError(f"Container {container_name} is not running.")
        return container_id

    def execute(self, command: str, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        """Execute a command in the Docker container and return the result as a dict."""
        cwd = cwd or self.config.cwd
        assert self.container_id, "Container not started"

        cmd = [self.config.executable, "exec", "-w", cwd]
        for key in self.config.forward_env:
            if (value := os.getenv(key)) is not None:
                cmd.extend(["-e", f"{key}={value}"])
        for key, value in self.config.env.items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.extend([self.container_id, "bash", "-lc", command])

        result = subprocess.run(
            cmd,
            text=True,
            timeout=timeout or self.config.timeout,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return {"output": result.stdout, "returncode": result.returncode}

    def cleanup(self):
        """Stop and remove the Docker container."""
        if self._manage_container and getattr(self, "container_id", None) is not None:
            cmd = f"(timeout 60 {self.config.executable} stop {self.container_id} || {self.config.executable} rm -f {self.container_id}) >/dev/null 2>&1 &"
            subprocess.Popen(cmd, shell=True)


    def __del__(self):
        """Cleanup container when object is destroyed."""
        self.cleanup()
