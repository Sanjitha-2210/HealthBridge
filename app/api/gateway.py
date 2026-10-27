"""API endpoints for M6 Consent & ABDM Security Gateway."""
import logging
from fastapi import APIRouter, status

from app.schemas.gateway import GatewayReleaseRequest, GatewayReleaseResponse
from app.services.gateway_service import GatewayService

logger = logging.getLogger("tn_healthbridge.api.gateway")

router = APIRouter(
    prefix="/gateway",
    tags=["Gateway"],
)


@router.post(
    "/release",
    response_model=GatewayReleaseResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
    summary="Secure Consent-Bound Health Data Release",
    description=(
        "Evaluates a synthetic ABDM-aligned consent artefact against an assembled FHIR R4 Bundle. "
        "Enforces strict fail-closed validation across 6 security gates (lifecycle status, temporal validity, "
        "data retention boundary, patient matching, HIU/HIP authorization, HI-type, and clinical date range). "
        "On full authorization, returns the release envelope with a SHA-256 integrity digest and the original, "
        "unmodified FHIR bundle. Zero central clinical persistence is created."
    ),
)
async def release_clinical_data(request: GatewayReleaseRequest) -> GatewayReleaseResponse:
    """Evaluate synthetic ABDM consent and securely release the unmodified FHIR bundle."""
    return GatewayService.evaluate_and_release(request)
