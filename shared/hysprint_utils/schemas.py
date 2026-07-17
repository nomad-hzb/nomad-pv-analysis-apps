"""
schemas.py
Shared Pydantic base models used across HySPRINT apps.
App-specific models live in each app's data_manager.py and inherit from these.
"""

from pydantic import BaseModel


class SampleMeta(BaseModel):
    """Metadata common to every sample across all measurement types."""
    sample_id: str
    variation: str = ""
    name: str = ""


class BatchInfo(BaseModel):
    """Basic batch identity fields."""
    lab_id: str
    upload_id: str | None = None
