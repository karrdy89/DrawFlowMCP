from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class SkillDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    client: str
    downloadUrl: str
    sha256: str
    expiresAt: str | None = None


class SkillLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: SkillDescriptor
    usage: str


class ImageDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int
    height: int
    scale: int


class DownloadDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["graph", "details"]
    artifactId: str
    format: Literal["png"] = "png"
    url: str
    contentType: Literal["image/png"] = "image/png"
    image: ImageDescriptor


class CreateDiagramPngDownloadLinksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagramId: str
    status: Literal["ready"]
    expiresAt: str
    downloads: list[DownloadDescriptor]
    warnings: list[str]
