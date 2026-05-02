from __future__ import annotations

from pathlib import Path
import os

from .errors import ConfigurationError


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "artifacts"
DEFAULT_PUBLIC_BASE_URL = "http://127.0.0.1:8765"
DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MAX_NODES = 80
DEFAULT_MAX_EDGES = 160
DEFAULT_MAX_CANVAS_PIXELS = 64_000_000


def artifact_dir() -> Path:
    return Path(os.environ.get("DRAWFLOW_ARTIFACT_DIR", str(DEFAULT_ARTIFACT_DIR))).resolve()


def public_base_url() -> str:
    return os.environ.get("DRAWFLOW_PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL).rstrip("/")


def ttl_seconds() -> int:
    return int(os.environ.get("DRAWFLOW_ARTIFACT_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))


def max_nodes() -> int:
    return int(os.environ.get("DRAWFLOW_MAX_NODES", str(DEFAULT_MAX_NODES)))


def max_edges() -> int:
    return int(os.environ.get("DRAWFLOW_MAX_EDGES", str(DEFAULT_MAX_EDGES)))


def max_canvas_pixels() -> int:
    return int(os.environ.get("DRAWFLOW_MAX_CANVAS_PIXELS", str(DEFAULT_MAX_CANVAS_PIXELS)))


def skill_path(version: str = "latest") -> Path:
    # MVP ships one local skill. Version routing is handled at the HTTP layer.
    return PROJECT_ROOT / "skills" / "drawflow" / "SKILL.md"
