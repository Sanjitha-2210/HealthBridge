"""FastAPI route handlers for M5 FHIR R4 Bundle Assembly Layer."""
from fastapi import APIRouter, status

from app.schemas.fhir import FhirBundleAssemblyRequest, FhirBundleAssemblyResponse
from app.services.fhir_service import FhirService

router = APIRouter(prefix="/fhir", tags=["FHIR Bundle Assembly"])


@router.post(
    "/bundle",
    response_model=FhirBundleAssemblyResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    summary="Assemble FHIR R4 Document Bundle",
    description=(
        "Assembles an uncertainty-aware, privacy-preserving FHIR R4 Document Bundle from an M3 terminology batch. "
        "Enforces two-tier section topology (Composition -> DiagnosticReport -> Observation), patient isolation, "
        "conservative preliminary status assignment, LOINC and UCUM compliance, and strict internal reference closure."
    ),
)
async def assemble_fhir_bundle(
    payload: FhirBundleAssemblyRequest,
) -> FhirBundleAssemblyResponse:
    """Evaluate and assemble a FHIR R4 Document Bundle from an M3 terminology batch."""
    return FhirService.assemble_bundle(payload)
