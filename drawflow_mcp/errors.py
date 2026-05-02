from __future__ import annotations


class DrawFlowError(Exception):
    code = "DRAWFLOW_ERROR"

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []

    def to_structured(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(DrawFlowError):
    code = "VALIDATION_FAILED"


class LayoutError(DrawFlowError):
    code = "LAYOUT_FAILED"


class RenderError(DrawFlowError):
    code = "RENDER_FAILED"


class ArtifactStoreError(DrawFlowError):
    code = "ARTIFACT_STORE_FAILED"


class ConfigurationError(DrawFlowError):
    code = "CONFIGURATION_ERROR"
