"""Pydantic schemas for M6 Consent & ABDM Security Gateway.

Defines synthetic ABDM-aligned consent models, release requests, and response envelopes.
NOTE: These schemas represent a synthetic simulation of the ABDM consent flow for
local validation and research. They are NOT certified against live NHA ABDM production endpoints.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.fhir import Bundle

ConsentStatus = Literal["GRANTED", "REVOKED", "EXPIRED", "DENIED", "REQUESTED"]
ConsentAccessMode = Literal["VIEW", "STORE", "STREAM", "QUERY"]


class ConsentDateRange(BaseModel):
    """Permitted clinical record date range bounded by the consent."""
    model_config = ConfigDict(extra="ignore")

    from_date: datetime = Field(..., description="Start of clinical record date range (inclusive).")
    to_date: datetime = Field(..., description="End of clinical record date range (inclusive).")


class ConsentPermission(BaseModel):
    """Permission details granted in the consent artefact."""
    model_config = ConfigDict(extra="ignore")

    access_mode: ConsentAccessMode = Field(
        default="VIEW",
        description="Access mode: VIEW, STORE, STREAM, or QUERY.",
    )
    date_range: ConsentDateRange = Field(
        ...,
        description="Clinical record date range authorized for release.",
    )
    data_erase_at: datetime = Field(
        ...,
        description="Data retention boundary after which the HIU must erase/purge released data.",
    )
    frequency: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional access frequency restrictions.",
    )


class ConsentPatient(BaseModel):
    """Patient subject identifying information in consent artefact."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Patient identifier or ABHA address (e.g. PAT-001 or user@sbx).")


class ConsentPurpose(BaseModel):
    """Clinical or operational purpose for data exchange."""
    model_config = ConfigDict(extra="ignore")

    code: str = Field(default="CAREMGT", description="ABDM Purpose code (e.g. CAREMGT, PUBHLTH, RESRCH).")
    text: Optional[str] = Field(default="Care Management", description="Human-readable purpose description.")
    ref_uri: Optional[str] = Field(default=None, description="Reference URI for purpose definition.")


class ConsentActor(BaseModel):
    """Healthcare entity (HIP or HIU) referenced in consent artefact."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique entity identifier (e.g. PRV-TN-CH-001 or HIU-TN-001).")
    name: Optional[str] = Field(default=None, description="Human-readable entity name.")


class ConsentRequester(BaseModel):
    """User or system requesting consent creation."""
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(default=None, description="Requester name.")
    identifier: Optional[Dict[str, Any]] = Field(default=None, description="Requester credentials or role.")


class AbdmConsentArtefact(BaseModel):
    """Synthetic ABDM-aligned Consent Artefact model.
    
    Represents an electronic consent record granted by a patient through an ABDM Consent Manager.
    """
    model_config = ConfigDict(extra="ignore")

    consent_id: str = Field(..., description="Unique UUID of the consent artefact.")
    status: ConsentStatus = Field(default="GRANTED", description="Current status of consent.")
    created_at: datetime = Field(..., description="Timestamp when consent was recorded.")
    patient: ConsentPatient = Field(..., description="Patient granting the consent.")
    purpose: ConsentPurpose = Field(default_factory=ConsentPurpose, description="Purpose of data access.")
    hip: Optional[ConsentActor] = Field(default=None, description="Health Information Provider holding the data.")
    hiu: ConsentActor = Field(..., description="Health Information User authorized to receive the data.")
    requester: Optional[ConsentRequester] = Field(default=None, description="Individual or role requesting access.")
    permission: ConsentPermission = Field(..., description="Permission boundaries (dates, retention, access mode).")
    consent_expiry: Optional[datetime] = Field(
        default=None,
        description="Temporal authorization expiry deadline. Distinct from data_erase_at (retention).",
    )
    hi_types: List[str] = Field(
        default_factory=lambda: ["DiagnosticReport"],
        description="Authorized Health Information Types (e.g. DiagnosticReport, Prescription).",
    )
    signature: Optional[str] = Field(
        default=None,
        description="Digital signature or synthetic test signature (e.g. TEST_SIG_<consent_id>).",
    )


class GatewayReleaseRequest(BaseModel):
    """Request payload for M6 secure data release."""
    model_config = ConfigDict(extra="ignore")

    consent: AbdmConsentArtefact = Field(..., description="ABDM consent artefact authorizing data access.")
    bundle: Bundle = Field(..., description="Assembled FHIR R4 document bundle to be released.")
    hiu_id: str = Field(..., description="Identifier of the Health Information User executing release.")
    hip_id: Optional[str] = Field(default=None, description="Optional HIP ID override/assertion.")
    allow_test_signatures: Optional[bool] = Field(
        default=None,
        description="Optional caller request indicator. Cannot override server configuration (ALLOW_TEST_SIGNATURES).",
    )


class GatewayReleaseResponse(BaseModel):
    """Response envelope for M6 secure data release."""
    model_config = ConfigDict(extra="ignore")

    release_id: str = Field(..., description="Unique UUID for this data release event.")
    status: Literal["released"] = Field(default="released", description="Release outcome status.")
    consent_id: str = Field(..., description="Consent artefact ID under which data was released.")
    hiu_id: str = Field(..., description="Health Information User receiving the released bundle.")
    hip_id: str = Field(..., description="Health Information Provider that sourced the bundle.")
    patient_reference: str = Field(..., description="Patient subject reference.")
    released_at: str = Field(..., description="ISO 8601 UTC timestamp of release.")
    observations_count: int = Field(..., description="Number of clinical observations released in bundle.")
    integrity_digest: str = Field(
        ...,
        description="Plain SHA-256 integrity digest over canonical release metadata and unmodified bundle.",
    )
    bundle: Bundle = Field(..., description="Original, unmodified FHIR R4 document bundle.")
