"""Service implementation for M6 Consent & ABDM Security Gateway.

Provides standalone consent verification and secure consent-bound FHIR data release.
Enforces zero central clinical storage, zero bundle mutation, and strict fail-closed
security evaluations across 6 gates.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from typing import Any, List, Optional, Set, Tuple
import uuid

from app.core.config import get_settings
from app.core.errors import (
    ConsentDateOutOfRangeError,
    ConsentDeniedError,
    ConsentExpiredError,
    ConsentHipMismatchError,
    ConsentHiTypeMismatchError,
    ConsentHiuMismatchError,
    ConsentNotGrantedError,
    ConsentPatientMismatchError,
    ConsentRetentionExpiredError,
    ConsentRevokedError,
    InvalidClinicalTimestampError,
    InvalidConsentSignatureError,
    InvalidGatewayRequestError,
)
from app.schemas.fhir import (
    Bundle,
    Composition,
    DiagnosticReport,
    Observation,
    Organization,
    Patient,
)
from app.schemas.gateway import (
    AbdmConsentArtefact,
    GatewayReleaseRequest,
    GatewayReleaseResponse,
)

logger = logging.getLogger("tn_healthbridge.gateway_service")

# Strict allowlist of legitimate resource types permitted in released FHIR documents
ALLOWED_RELEASE_RESOURCE_TYPES: Set[str] = {
    "Composition",
    "Patient",
    "Organization",
    "Specimen",
    "DiagnosticReport",
    "Observation",
}

MAX_CLOCK_DRIFT_MINUTES: int = 5
MAX_CONSENT_VALIDITY_DAYS: int = 180


def _to_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get_res_type(res: Any) -> str:
    """Safely extract resourceType from Pydantic model or dict."""
    if hasattr(res, "resourceType"):
        return str(res.resourceType)
    if isinstance(res, dict):
        return str(res.get("resourceType", ""))
    return ""


def _get_res_id(res: Any) -> str:
    """Safely extract id from Pydantic model or dict."""
    if hasattr(res, "id"):
        return str(res.id)
    if isinstance(res, dict):
        return str(res.get("id", ""))
    return ""


class GatewayService:
    """Stateless, zero-persistence ABDM Security & Consent Gatekeeper."""

    @staticmethod
    def verify_consent(
        consent: AbdmConsentArtefact,
        allow_test_signatures: Optional[bool] = None,
        evaluation_time: Optional[datetime] = None,
    ) -> bool:
        """Standalone internal service function for consent artefact verification.
        
        Validates:
        1. Consent CreatedAt Clock Drift (at most 5 minutes into the future).
        2. Consent Status (must be GRANTED).
        3. Consent Temporal Validity / Expiry (eval_time <= consent_expiry or default 180d cap).
        4. Data Retention Boundary (eval_time < data_erase_at).
        5. Date Range Sanity (from_date <= to_date).
        6. Signature Verification (server-side trusted configuration control).
        
        Raises appropriate GatewayException subclasses on any violation.
        """
        eval_utc = _to_utc(evaluation_time or datetime.now(timezone.utc))
        created_utc = _to_utc(consent.created_at)

        # Gate 0: Clock drift validation (created_at cannot be far in the future)
        max_allowed_future = eval_utc + timedelta(minutes=MAX_CLOCK_DRIFT_MINUTES)
        if created_utc > max_allowed_future:
            raise InvalidGatewayRequestError(
                f"Consent artefact created_at timestamp is in the future beyond allowable clock drift ({MAX_CLOCK_DRIFT_MINUTES} minutes)."
            )

        # Gate 1: Consent Lifecycle Status Check
        if consent.status == "EXPIRED":
            raise ConsentExpiredError("Consent artefact status is EXPIRED.")
        if consent.status == "REVOKED":
            raise ConsentRevokedError("Consent artefact status is REVOKED by the patient.")
        if consent.status == "DENIED":
            raise ConsentDeniedError("Consent request was DENIED by the patient.")
        if consent.status == "REQUESTED":
            raise ConsentNotGrantedError("Consent artefact status is REQUESTED; authorization has not been granted.")
        if consent.status != "GRANTED":
            raise ConsentNotGrantedError(f"Consent artefact is in invalid or ungranted status: '{consent.status}'.")

        # Gate 2: Consent Authorization Expiry (distinct from data retention)
        if consent.consent_expiry is not None:
            expiry_utc = _to_utc(consent.consent_expiry)
            if expiry_utc < created_utc:
                raise InvalidGatewayRequestError(
                    "Consent authorization expiry cannot be earlier than created_at."
                )
            if eval_utc > expiry_utc:
                raise ConsentExpiredError("Consent authorization has expired.")
        else:
            # Safe default maximum validity period when expiry is omitted
            default_expiry_utc = created_utc + timedelta(days=MAX_CONSENT_VALIDITY_DAYS)
            if eval_utc > default_expiry_utc:
                raise ConsentExpiredError(
                    f"Consent authorization has expired under default maximum validity period ({MAX_CONSENT_VALIDITY_DAYS} days)."
                )

        # Gate 3: Data Retention / Erasure Boundary Check
        erase_utc = _to_utc(consent.permission.data_erase_at)
        if eval_utc >= erase_utc:
            raise ConsentRetentionExpiredError(
                "Data retention period has expired under data_erase_at boundary."
            )

        # Gate 4: Permitted Clinical Date Range Sanity Check
        from_utc = _to_utc(consent.permission.date_range.from_date)
        to_utc = _to_utc(consent.permission.date_range.to_date)
        if from_utc > to_utc:
            raise InvalidGatewayRequestError(
                "Consent clinical date_range from_date cannot be later than to_date."
            )

        # Gate 5: Digital Signature Check (Strict Server-Side Trusted Configuration)
        settings = get_settings()
        server_permits_test = settings.ALLOW_TEST_SIGNATURES and (settings.ENVIRONMENT in ("development", "test"))

        if allow_test_signatures is None:
            effective_allow_test = server_permits_test
        else:
            # Caller cannot override a disabled server setting
            effective_allow_test = server_permits_test and allow_test_signatures

        if not effective_allow_test:
            if consent.signature and consent.signature.startswith("TEST_SIG_"):
                raise InvalidConsentSignatureError(
                    "Synthetic test signatures are forbidden because server configuration disables test signatures or runs in production."
                )
            raise InvalidConsentSignatureError(
                "Cryptographic signature verification requires production PKI gateway. "
                "Synthetic test signatures are disabled by server configuration."
            )
        else:
            # Server permits test signatures -> verify synthetic test signature contract
            if not consent.signature:
                raise InvalidConsentSignatureError("Missing consent signature.")
            expected_test_sig = f"TEST_SIG_{consent.consent_id}"
            if consent.signature != expected_test_sig:
                raise InvalidConsentSignatureError("Invalid synthetic test signature.")

        return True

    @classmethod
    def evaluate_and_release(
        cls,
        request: GatewayReleaseRequest,
        evaluation_time: Optional[datetime] = None,
    ) -> GatewayReleaseResponse:
        """Evaluate synthetic ABDM consent and release the unmodified FHIR R4 Bundle.
        
        Enforces 6 Security Gates:
        1. Consent Verification (Status, Expiry, Retention, Signature).
        2. Bundle Structural Integrity & Strict Allowlist Resource Extraction.
        3. Patient Identity Matching (fail-closed on mismatch/ambiguity).
        4. HIU and HIP Authorization.
        5. HI-Type Eligibility ('DiagnosticReport').
        6. Clinical Date Bounding across all Observations (fail-safe rejection, zero bundle mutation).
        
        Returns GatewayReleaseResponse with plain SHA-256 integrity digest and the exact bundle.
        """
        eval_utc = _to_utc(evaluation_time or datetime.now(timezone.utc))

        # 1. Determine effective test signature permission based on server config
        settings = get_settings()
        server_permits_test = settings.ALLOW_TEST_SIGNATURES and (settings.ENVIRONMENT in ("development", "test"))
        if request.allow_test_signatures is None:
            effective_allow_test = server_permits_test
        else:
            effective_allow_test = server_permits_test and request.allow_test_signatures

        cls.verify_consent(
            request.consent,
            allow_test_signatures=effective_allow_test,
            evaluation_time=eval_utc,
        )

        bundle: Bundle = request.bundle

        # 2. Bundle Structural Integrity
        if not bundle.entry:
            raise InvalidGatewayRequestError("FHIR bundle contains no entries.")
        if bundle.type != "document":
            raise InvalidGatewayRequestError(f"FHIR bundle type must be 'document', got '{bundle.type}'.")

        patient_entries: List[Any] = []
        org_entries: List[Any] = []
        comp_entries: List[Any] = []
        dr_entries: List[Any] = []
        obs_entries: List[Any] = []
        spec_entries: List[Any] = []

        for e in bundle.entry:
            res = e.resource
            rtype = _get_res_type(res)

            # Strict Resource Type Allowlist Check
            if rtype not in ALLOWED_RELEASE_RESOURCE_TYPES:
                raise InvalidGatewayRequestError(
                    f"Bundle contains unexpected or unapproved resource type '{rtype}'; release forbidden under security allowlist."
                )

            if rtype == "Patient":
                patient_entries.append(res)
            elif rtype == "Organization":
                org_entries.append(res)
            elif rtype == "Composition":
                comp_entries.append(res)
            elif rtype == "DiagnosticReport":
                dr_entries.append(res)
            elif rtype == "Observation":
                obs_entries.append(res)
            elif rtype == "Specimen":
                spec_entries.append(res)

        if len(patient_entries) == 0:
            raise InvalidGatewayRequestError("FHIR bundle must contain a Patient resource.")
        if len(patient_entries) > 1:
            raise InvalidGatewayRequestError(
                f"FHIR bundle contains {len(patient_entries)} Patient resources; ambiguous identity."
            )
        patient_res = patient_entries[0]
        patient_id = _get_res_id(patient_res)

        if len(org_entries) == 0:
            raise InvalidGatewayRequestError("FHIR bundle must contain an Organization resource.")
        org_res = org_entries[0]

        if len(obs_entries) == 0:
            raise InvalidGatewayRequestError("FHIR bundle contains no Observation resources to release.")

        # 3. Patient Identity Matching Gate
        consent_pt_id = request.consent.patient.id.strip()
        patient_identifiers: List[str] = []

        if hasattr(patient_res, "identifier") and patient_res.identifier:
            for ident in patient_res.identifier:
                if hasattr(ident, "value") and ident.value:
                    patient_identifiers.append(str(ident.value).strip())
                elif isinstance(ident, dict) and ident.get("value"):
                    patient_identifiers.append(str(ident["value"]).strip())
        elif isinstance(patient_res, dict) and "identifier" in patient_res:
            for ident in patient_res["identifier"]:
                if isinstance(ident, dict) and ident.get("value"):
                    patient_identifiers.append(str(ident["value"]).strip())

        if not patient_identifiers:
            raise ConsentPatientMismatchError("Bundle Patient resource contains no valid identifier values.")

        # Check match against identifiers or logical id
        matched_patient = (consent_pt_id in patient_identifiers) or (consent_pt_id == patient_id)
        if not matched_patient:
            # Privacy-safe sanitized error message: do NOT echo bundle patient identifiers
            raise ConsentPatientMismatchError(
                "Patient identity in consent artefact does not match bundle subject."
            )

        # Cross-resource patient isolation audit (Composition, DiagnosticReport, Observation, Specimen)
        expected_subject_ref = f"urn:uuid:{patient_id}"
        alt_subject_ref = f"Patient/{patient_id}"

        def check_subject(res: Any, res_name: str) -> None:
            sub = getattr(res, "subject", None) if hasattr(res, "subject") else (res.get("subject") if isinstance(res, dict) else None)
            ref_val = None
            if hasattr(sub, "reference"):
                ref_val = sub.reference
            elif isinstance(sub, dict):
                ref_val = sub.get("reference")
            if ref_val not in (expected_subject_ref, alt_subject_ref):
                # Privacy-safe sanitized error message: omit raw reference UUIDs
                raise ConsentPatientMismatchError(
                    f"Patient isolation violation: {res_name} subject reference does not match bundle Patient reference."
                )

        for comp in comp_entries:
            check_subject(comp, "Composition")
        for dr in dr_entries:
            check_subject(dr, "DiagnosticReport")
        for obs in obs_entries:
            check_subject(obs, "Observation")
        for spec in spec_entries:
            check_subject(spec, "Specimen")

        # 4. HIU Authorization Gate
        request_hiu = request.hiu_id.strip()
        consented_hiu = request.consent.hiu.id.strip()
        if request_hiu != consented_hiu:
            # Privacy-safe sanitized error message
            raise ConsentHiuMismatchError(
                "Requesting HIU does not match consented HIU."
            )

        # 5. HIP Authorization Gate
        org_identifiers: List[str] = []
        if hasattr(org_res, "identifier") and org_res.identifier:
            for ident in org_res.identifier:
                if hasattr(ident, "value") and ident.value:
                    org_identifiers.append(str(ident.value).strip())
                elif isinstance(ident, dict) and ident.get("value"):
                    org_identifiers.append(str(ident["value"]).strip())
        elif isinstance(org_res, dict) and "identifier" in org_res:
            for ident in org_res["identifier"]:
                if isinstance(ident, dict) and ident.get("value"):
                    org_identifiers.append(str(ident["value"]).strip())

        source_provider = org_identifiers[0] if org_identifiers else _get_res_id(org_res)

        if request.consent.hip is not None:
            consented_hip = request.consent.hip.id.strip()
            if consented_hip not in org_identifiers and consented_hip != _get_res_id(org_res):
                raise ConsentHipMismatchError(
                    "Consented HIP does not match bundle source provider organization."
                )
            if request.hip_id and request.hip_id.strip() != consented_hip:
                raise ConsentHipMismatchError(
                    "Supplied hip_id does not match consented HIP."
                )

        # 6. HI-Type Eligibility Gate
        if "DiagnosticReport" not in request.consent.hi_types:
            raise ConsentHiTypeMismatchError(
                "Consent does not authorize 'DiagnosticReport' health information type."
            )

        # 7. Clinical Date Bounding Gate (Fail-Safe Rejection, HTTP 403, Zero Pruning)
        from_utc = _to_utc(request.consent.permission.date_range.from_date)
        to_utc = _to_utc(request.consent.permission.date_range.to_date)

        for obs in obs_entries:
            raw_dt = getattr(obs, "effectiveDateTime", None) if hasattr(obs, "effectiveDateTime") else (obs.get("effectiveDateTime") if isinstance(obs, dict) else None)
            obs_id = _get_res_id(obs)

            if not raw_dt or not str(raw_dt).strip():
                # Privacy-safe sanitized error message
                raise InvalidClinicalTimestampError(
                    "Observation is missing effectiveDateTime clinical timestamp; fail-closed rejection."
                )

            str_dt = str(raw_dt).strip()
            try:
                # Handle ISO 8601 timestamps
                parsed_dt = datetime.fromisoformat(str_dt.replace("Z", "+00:00"))
            except ValueError:
                # Privacy-safe sanitized error message: do not echo raw corrupted data
                raise InvalidClinicalTimestampError(
                    "Observation contains unparseable effectiveDateTime clinical timestamp; fail-closed rejection."
                )

            obs_utc = _to_utc(parsed_dt)

            if obs_utc < from_utc or obs_utc > to_utc:
                # Privacy-safe sanitized error message: do not echo patient clinical observation timestamps
                raise ConsentDateOutOfRangeError(
                    "One or more observations fall outside the consented clinical date range. "
                    "Entire release rejected without modification."
                )

        # 8. Integrity Digest Generation (Plain SHA-256 Digest over canonical metadata + unmodified bundle)
        release_id = str(uuid.uuid4())
        released_at_str = eval_utc.isoformat()

        bundle_json = bundle.model_dump_json(exclude_none=True)
        canonical_header = (
            f"release_v1|"
            f"{request.consent.consent_id}|"
            f"{consent_pt_id}|"
            f"{request_hiu}|"
            f"{source_provider}|"
            f"{bundle.id}|"
            f"{len(obs_entries)}"
        )
        digest_input = f"{canonical_header}||{bundle_json}".encode("utf-8")
        integrity_digest = hashlib.sha256(digest_input).hexdigest()

        logger.info(
            "M6 Data Release authorized: release_id=%s, observations=%d",
            release_id,
            len(obs_entries),
        )

        return GatewayReleaseResponse(
            release_id=release_id,
            status="released",
            consent_id=request.consent.consent_id,
            hiu_id=request_hiu,
            hip_id=source_provider,
            patient_reference=patient_identifiers[0],
            released_at=released_at_str,
            observations_count=len(obs_entries),
            integrity_digest=integrity_digest,
            bundle=bundle,
        )
