"""Safe document builders for TXT/DOCX/PDF/PPTX/XLSX (MIND-02)."""
from .builder import build_artifact, validate_artifact, ARTIFACT_FORMATS

__all__ = ['build_artifact', 'validate_artifact', 'ARTIFACT_FORMATS']
