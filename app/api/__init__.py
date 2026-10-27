from app.api.ingestion import router as ingestion_router
from app.api.normalization import router as normalization_router
from app.api.terminology import router as terminology_router
from app.api.identity import router as identity_router
from app.api.fhir import router as fhir_router
from app.api.gateway import router as gateway_router

__all__ = [
    "ingestion_router",
    "normalization_router",
    "terminology_router",
    "identity_router",
    "fhir_router",
    "gateway_router",
]


