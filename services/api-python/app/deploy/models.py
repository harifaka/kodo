"""Typed responses for the local Docker control panel (wire format is camelCase)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

DEFAULT_LOG_TAIL = 200
MAX_LOG_TAIL = 1000


class DockerModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ContainerInfo(DockerModel):
    name: str
    service: str
    state: str
    status: str
    health: str = "unknown"
    ports: list[str] = Field(default_factory=list)


class DockerStatus(DockerModel):
    docker_available: bool
    daemon_running: bool
    has_compose_file: bool
    containers: list[ContainerInfo] = Field(default_factory=list)
    warning: str | None = None


class ComposeResult(DockerModel):
    success: bool
    command: str
    stdout: str = ""
    stderr: str = ""
    status: DockerStatus
    warning: str | None = None


class ComposeLogs(DockerModel):
    service: str | None = None
    tail: int = DEFAULT_LOG_TAIL
    logs: str = ""
    warning: str | None = None


__all__ = [
    "DEFAULT_LOG_TAIL",
    "MAX_LOG_TAIL",
    "ComposeLogs",
    "ComposeResult",
    "ContainerInfo",
    "DockerModel",
    "DockerStatus",
]
