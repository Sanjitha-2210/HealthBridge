"""Comprehensive test suite for M6 Consent & ABDM Security Gateway."""
import copy
from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

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
from app.main import app
from app.schemas.fhir import (
    Bundle,
    BundleEntry,
    FhirBundleAssemblyRequest,
)
from app.schemas.gateway import (
    AbdmConsentArtefact,
    ConsentActor,
    ConsentDateRange,
    ConsentPatient,
    ConsentPermission,
    ConsentPurpose,
    GatewayReleaseRequest,
)
from app.services.fhir_service import FhirService
from app.services.gateway_service import GatewayService
from tests.test_fhir import make_mapped_record, make_terminology_batch

client = TestClient(app)
settings = get_settings()

FIXED_NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Enable synthetic test signatures in development/test environment by default for tests."""
    monkeypatch.setattr(settings, "ALLOW_TEST_SIGNATURES", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")


def make_test_bundle(
    patient_id: str = "PT-2026-0091",
    provider_id: str = "PRV-GHT-01",
    observed_at: str = "2026-10-27T10:15:00+00:00",
) -> Bundle:
    """Helper to assemble a valid M5 FHIR document Bundle for testing."""
    record = make_mapped_record(
        index=0,
        patient_ref=patient_id,
        test_name="Fasting Blood Glucose",
        result=110.0,
        unit="mg/dL",
        observed_at=observed_at,
        specimen="Serum",
    )
    batch_dict = make_terminology_batch([record], provider_id=provider_id)
    req = FhirBundleAssemblyRequest.model_validate({"batch": batch_dict})
    assembly_resp = FhirService.assemble_bundle(req)
    return assembly_resp.bundle


def make_test_consent(
    consent_id: Optional[str] = None,
    patient_id: str = "PT-2026-0091",
    hiu_id: str = "HIU-TN-001",
    hip_id: str = "PRV-GHT-01",
    status: str = "GRANTED",
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    data_erase_at: Optional[datetime] = None,
    consent_expiry: Optional[datetime] = None,
    created_at: Optional[datetime] = None,
    hi_types: Optional[List[str]] = None,
    signature: Optional[str] = None,
) -> AbdmConsentArtefact:
    """Helper to create a synthetic ABDM-aligned consent artefact for testing."""
    cid = consent_id or str(uuid.uuid4())
    f_date = from_date or (FIXED_NOW - timedelta(days=7))
    t_date = to_date or (FIXED_NOW + timedelta(days=1))
    erase_date = data_erase_at or (FIXED_NOW + timedelta(days=30))
    c_date = created_at or (FIXED_NOW - timedelta(days=1))
    sig = signature if signature is not None else f"TEST_SIG_{cid}"

    return AbdmConsentArtefact(
        consent_id=cid,
        status=status,  # type: ignore[arg-type]
        created_at=c_date,
        patient=ConsentPatient(id=patient_id),
        purpose=ConsentPurpose(code="CAREMGT", text="Care Management"),
        hip=ConsentActor(id=hip_id, name="General Hospital Provider"),
        hiu=ConsentActor(id=hiu_id, name="City Health Information User"),
        permission=ConsentPermission(
            access_mode="VIEW",
            date_range=ConsentDateRange(from_date=f_date, to_date=t_date),
            data_erase_at=erase_date,
        ),
        consent_expiry=consent_expiry,
        hi_types=hi_types if hi_types is not None else ["DiagnosticReport"],
        signature=sig,
    )


# ============================================================================
# Section 1: Standalone Consent Verification (Service Function) Tests
# ============================================================================

def test_consent_granted_valid():
    """Verify that a GRANTED consent with valid dates passes verification."""
    consent = make_test_consent()
    assert GatewayService.verify_consent(
        consent,
        allow_test_signatures=True,
        evaluation_time=FIXED_NOW,
    ) is True


def test_consent_expired_status_rejected():
    """Verify that consent in EXPIRED status raises ConsentExpiredError."""
    consent = make_test_consent(status="EXPIRED")
    with pytest.raises(ConsentExpiredError, match="status is EXPIRED"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_revoked_status_rejected():
    """Verify that consent in REVOKED status raises ConsentRevokedError."""
    consent = make_test_consent(status="REVOKED")
    with pytest.raises(ConsentRevokedError, match="status is REVOKED"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_denied_status_rejected():
    """Verify that consent in DENIED status raises ConsentDeniedError."""
    consent = make_test_consent(status="DENIED")
    with pytest.raises(ConsentDeniedError, match="DENIED"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_requested_status_rejected():
    """Verify that consent in REQUESTED status raises ConsentNotGrantedError."""
    consent = make_test_consent(status="REQUESTED")
    with pytest.raises(ConsentNotGrantedError, match="status is REQUESTED"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_temporal_expiry_evaluated():
    """Verify that consent with expired consent_expiry raises ConsentExpiredError."""
    consent = make_test_consent(
        consent_expiry=FIXED_NOW - timedelta(hours=1),
    )
    with pytest.raises(ConsentExpiredError, match="authorization has expired"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_temporal_validity_active():
    """Verify that consent with active consent_expiry in the future passes."""
    consent = make_test_consent(
        consent_expiry=FIXED_NOW + timedelta(hours=24),
    )
    assert GatewayService.verify_consent(
        consent,
        allow_test_signatures=True,
        evaluation_time=FIXED_NOW,
    ) is True


def test_consent_retention_data_erase_at_passed():
    """Verify that reaching data_erase_at retention boundary raises ConsentRetentionExpiredError."""
    consent = make_test_consent(
        data_erase_at=FIXED_NOW - timedelta(minutes=5),
    )
    with pytest.raises(ConsentRetentionExpiredError, match="data_erase_at"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_distinction_expiry_vs_erase_at():
    """Verify distinct semantic evaluation between consent authorization expiry and data retention."""
    # Active authorization but expired retention deadline -> fails retention check
    c1 = make_test_consent(
        consent_expiry=FIXED_NOW + timedelta(days=2),
        data_erase_at=FIXED_NOW - timedelta(minutes=1),
    )
    with pytest.raises(ConsentRetentionExpiredError):
        GatewayService.verify_consent(c1, allow_test_signatures=True, evaluation_time=FIXED_NOW)

    # Expired authorization but future retention deadline -> fails authorization check
    c2 = make_test_consent(
        consent_expiry=FIXED_NOW - timedelta(minutes=1),
        data_erase_at=FIXED_NOW + timedelta(days=30),
    )
    with pytest.raises(ConsentExpiredError):
        GatewayService.verify_consent(c2, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_inverted_date_range_rejected():
    """Verify that an inverted clinical date range (from_date > to_date) is rejected."""
    consent = make_test_consent(
        from_date=FIXED_NOW + timedelta(days=5),
        to_date=FIXED_NOW - timedelta(days=5),
    )
    with pytest.raises(InvalidGatewayRequestError, match="cannot be later than to_date"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


# ============================================================================
# Section 1B: Timestamp Validity, Clock Drift & Safe Default Expiry (SEC-M6-05)
# ============================================================================

def test_consent_created_at_future_drift_within_5_minutes_accepted():
    """Verify that created_at up to 5 minutes in the future is accepted under clock drift policy."""
    consent = make_test_consent(created_at=FIXED_NOW + timedelta(minutes=3))
    assert GatewayService.verify_consent(
        consent,
        allow_test_signatures=True,
        evaluation_time=FIXED_NOW,
    ) is True


def test_consent_created_at_future_drift_beyond_5_minutes_rejected():
    """Verify that created_at more than 5 minutes in the future is rejected."""
    consent = make_test_consent(created_at=FIXED_NOW + timedelta(minutes=6))
    with pytest.raises(InvalidGatewayRequestError, match="in the future beyond allowable clock drift"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_expiry_earlier_than_created_at_rejected():
    """Verify that consent_expiry earlier than created_at is rejected as invalid."""
    consent = make_test_consent(
        created_at=FIXED_NOW - timedelta(days=2),
        consent_expiry=FIXED_NOW - timedelta(days=3),
    )
    with pytest.raises(InvalidGatewayRequestError, match="expiry cannot be earlier than created_at"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_consent_missing_expiry_within_180_days_valid():
    """Verify that when consent_expiry is omitted, authorization remains valid within 180 days."""
    consent = make_test_consent(
        created_at=FIXED_NOW - timedelta(days=90),
        consent_expiry=None,
    )
    assert GatewayService.verify_consent(
        consent,
        allow_test_signatures=True,
        evaluation_time=FIXED_NOW,
    ) is True


def test_consent_missing_expiry_beyond_180_days_rejected():
    """Verify that when consent_expiry is omitted, authorization expires after 180 days default window."""
    consent = make_test_consent(
        created_at=FIXED_NOW - timedelta(days=181),
        consent_expiry=None,
    )
    with pytest.raises(ConsentExpiredError, match="default maximum validity period"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


# ============================================================================
# Section 2: Server-Side Test Signature Control & Isolation (SEC-M6-01)
# ============================================================================

def test_signature_server_setting_disabled_rejects_synthetic_signature(monkeypatch):
    """Verify that when server configuration has ALLOW_TEST_SIGNATURES=False, synthetic signatures are rejected."""
    monkeypatch.setattr(settings, "ALLOW_TEST_SIGNATURES", False)
    consent = make_test_consent()
    with pytest.raises(InvalidConsentSignatureError, match="Synthetic test signatures are forbidden"):
        GatewayService.verify_consent(consent, evaluation_time=FIXED_NOW)


def test_signature_server_setting_disabled_cannot_be_overridden_by_request_flag(monkeypatch):
    """Verify that a caller setting allow_test_signatures=True cannot override disabled server configuration."""
    monkeypatch.setattr(settings, "ALLOW_TEST_SIGNATURES", False)
    consent = make_test_consent()
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=make_test_bundle(),
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,  # Caller attempts bypass
    )
    with pytest.raises(InvalidConsentSignatureError, match="Synthetic test signatures are forbidden"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_signature_production_environment_rejects_synthetic_signature(monkeypatch):
    """Verify that synthetic test signatures are strictly forbidden in production environment."""
    monkeypatch.setattr(settings, "ALLOW_TEST_SIGNATURES", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    consent = make_test_consent()
    with pytest.raises(InvalidConsentSignatureError, match="runs in production"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_signature_missing_when_test_flag_disabled(monkeypatch):
    """Verify that missing signature is rejected when test signatures are disabled."""
    monkeypatch.setattr(settings, "ALLOW_TEST_SIGNATURES", False)
    consent = make_test_consent(signature="")
    with pytest.raises(InvalidConsentSignatureError, match="Cryptographic signature verification requires production PKI"):
        GatewayService.verify_consent(consent, evaluation_time=FIXED_NOW)


def test_signature_valid_synthetic_when_server_permits_in_test_env():
    """Verify that valid synthetic test signature (TEST_SIG_<consent_id>) passes when server permits."""
    cid = str(uuid.uuid4())
    consent = make_test_consent(consent_id=cid, signature=f"TEST_SIG_{cid}")
    assert GatewayService.verify_consent(
        consent,
        allow_test_signatures=True,
        evaluation_time=FIXED_NOW,
    ) is True


def test_signature_invalid_synthetic_when_server_permits():
    """Verify that mismatched synthetic test signature is rejected when server permits test mode."""
    cid = str(uuid.uuid4())
    consent = make_test_consent(consent_id=cid, signature="TEST_SIG_WRONG_ID")
    with pytest.raises(InvalidConsentSignatureError, match="Invalid synthetic test signature"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


def test_signature_missing_when_server_permits():
    """Verify that missing signature raises InvalidConsentSignatureError even when test mode permitted."""
    consent = make_test_consent(signature="")
    with pytest.raises(InvalidConsentSignatureError, match="Missing consent signature"):
        GatewayService.verify_consent(consent, allow_test_signatures=True, evaluation_time=FIXED_NOW)


# ============================================================================
# Section 3: Patient Matching, Patient Isolation & Specimen Linkage (SEC-M6-04)
# ============================================================================

def test_patient_match_success():
    """Verify successful release when consent patient matches bundle patient."""
    bundle = make_test_bundle(patient_id="PT-2026-0091")
    consent = make_test_consent(patient_id="PT-2026-0091")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    resp = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)
    assert resp.status == "released"
    assert resp.patient_reference == "PT-2026-0091"
    assert resp.observations_count == 1


def test_patient_mismatch_rejected():
    """Verify that mismatched patient identity between consent and bundle raises ConsentPatientMismatchError."""
    bundle = make_test_bundle(patient_id="PT-2026-0091")
    consent = make_test_consent(patient_id="PT-OTHER-9999")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentPatientMismatchError, match="Patient identity in consent artefact does not match bundle subject"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_patient_resource_missing_identifier():
    """Verify fail-closed rejection if bundle Patient resource has no identifier values."""
    bundle = make_test_bundle(patient_id="PT-2026-0091")
    for entry in bundle.entry:
        if hasattr(entry.resource, "resourceType") and entry.resource.resourceType == "Patient":
            entry.resource.identifier = []

    consent = make_test_consent(patient_id="PT-2026-0091")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentPatientMismatchError, match="contains no valid identifier"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_patient_cross_resource_isolation_violation():
    """Verify that an Observation pointing to a different subject raises ConsentPatientMismatchError."""
    bundle = make_test_bundle(patient_id="PT-2026-0091")
    for entry in bundle.entry:
        if hasattr(entry.resource, "resourceType") and entry.resource.resourceType == "Observation":
            entry.resource.subject.reference = "urn:uuid:00000000-0000-0000-0000-000000000000"

    consent = make_test_consent(patient_id="PT-2026-0091")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentPatientMismatchError, match="Patient isolation violation: Observation subject reference"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_specimen_subject_mismatch_rejected():
    """Verify that a Specimen pointing to a different subject raises ConsentPatientMismatchError."""
    bundle = make_test_bundle(patient_id="PT-2026-0091")
    # Mutate specimen subject
    for entry in bundle.entry:
        if hasattr(entry.resource, "resourceType") and entry.resource.resourceType == "Specimen":
            entry.resource.subject.reference = "urn:uuid:00000000-0000-0000-0000-000000000000"

    consent = make_test_consent(patient_id="PT-2026-0091")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentPatientMismatchError, match="Patient isolation violation: Specimen subject reference"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_unexpected_resource_type_rejected():
    """Verify that a bundle containing an unapproved resource type (e.g. Condition) is rejected."""
    bundle = make_test_bundle(patient_id="PT-2026-0091")
    # Inject an unexpected resource type
    unapproved_entry = BundleEntry(
        fullUrl="urn:uuid:11111111-2222-3333-4444-555555555555",
        resource={
            "resourceType": "Condition",
            "id": "cond-1",
            "clinicalStatus": "active",
        },
    )
    bundle.entry.append(unapproved_entry)

    consent = make_test_consent(patient_id="PT-2026-0091")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(InvalidGatewayRequestError, match="unexpected or unapproved resource type 'Condition'"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


# ============================================================================
# Section 4: HIU and HIP Authorization Gate Tests
# ============================================================================

def test_hiu_match_success():
    """Verify release succeeds when requesting HIU matches consented HIU."""
    bundle = make_test_bundle()
    consent = make_test_consent(hiu_id="HIU-TN-001")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    resp = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)
    assert resp.hiu_id == "HIU-TN-001"


def test_hiu_mismatch_rejected():
    """Verify that unauthorized requesting HIU raises ConsentHiuMismatchError."""
    bundle = make_test_bundle()
    consent = make_test_consent(hiu_id="HIU-TN-001")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-MALICIOUS-ROUTER",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentHiuMismatchError, match="Requesting HIU does not match consented HIU"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_hip_match_success():
    """Verify release succeeds when consented HIP matches bundle source provider."""
    bundle = make_test_bundle(provider_id="PRV-GHT-01")
    consent = make_test_consent(hip_id="PRV-GHT-01")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    resp = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)
    assert resp.hip_id == "PRV-GHT-01"


def test_hip_mismatch_rejected():
    """Verify that mismatched HIP in consent raises ConsentHipMismatchError."""
    bundle = make_test_bundle(provider_id="PRV-GHT-01")
    consent = make_test_consent(hip_id="PRV-DIFFERENT-99")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentHipMismatchError, match="Consented HIP does not match bundle source provider"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_hip_override_mismatch_rejected():
    """Verify that conflicting hip_id parameter in release request raises ConsentHipMismatchError."""
    bundle = make_test_bundle(provider_id="PRV-GHT-01")
    consent = make_test_consent(hip_id="PRV-GHT-01")
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        hip_id="PRV-CONFLICT-02",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentHipMismatchError, match="Supplied hip_id does not match consented HIP"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


# ============================================================================
# Section 5: HI-Type Eligibility Gate Tests
# ============================================================================

def test_hi_type_diagnostic_report_authorized():
    """Verify that DiagnosticReport hi_type is accepted."""
    bundle = make_test_bundle()
    consent = make_test_consent(hi_types=["DiagnosticReport", "OPConsultation"])
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    resp = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)
    assert resp.status == "released"


def test_hi_type_prescription_only_rejected():
    """Verify that consent without DiagnosticReport raises ConsentHiTypeMismatchError."""
    bundle = make_test_bundle()
    consent = make_test_consent(hi_types=["Prescription"])
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentHiTypeMismatchError, match="DiagnosticReport"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_hi_type_empty_rejected():
    """Verify that empty hi_types list raises ConsentHiTypeMismatchError."""
    bundle = make_test_bundle()
    consent = make_test_consent(hi_types=[])
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentHiTypeMismatchError):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


# ============================================================================
# Section 6: Clinical Date Bounding Gate (Fail-Safe Rejection & Zero Mutation)
# ============================================================================

def test_clinical_date_within_bounds_success():
    """Verify release succeeds when observation timestamp falls strictly inside consented range."""
    bundle = make_test_bundle(observed_at="2026-10-27T10:15:00+00:00")
    consent = make_test_consent(
        from_date=datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc),
        to_date=datetime(2026, 10, 28, 0, 0, 0, tzinfo=timezone.utc),
    )
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    resp = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)
    assert resp.status == "released"


def test_clinical_date_exact_boundary_inclusive():
    """Verify that clinical date range comparison is boundary-inclusive (from_date and to_date)."""
    from_boundary = datetime(2026, 10, 27, 10, 15, 0, tzinfo=timezone.utc)
    to_boundary = datetime(2026, 10, 27, 10, 15, 0, tzinfo=timezone.utc)

    bundle = make_test_bundle(observed_at="2026-10-27T10:15:00+00:00")
    consent = make_test_consent(
        from_date=from_boundary,
        to_date=to_boundary,
    )
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    resp = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)
    assert resp.status == "released"


def test_clinical_date_before_from_date_rejected():
    """Verify that an observation prior to from_date rejects the ENTIRE release without pruning."""
    bundle = make_test_bundle(observed_at="2026-10-15T08:00:00+00:00")
    consent = make_test_consent(
        from_date=datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc),
        to_date=datetime(2026, 10, 28, 0, 0, 0, tzinfo=timezone.utc),
    )
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentDateOutOfRangeError, match="fall outside the consented clinical date range"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_clinical_date_after_to_date_rejected():
    """Verify that an observation after to_date rejects the ENTIRE release without pruning."""
    bundle = make_test_bundle(observed_at="2026-10-30T08:00:00+00:00")
    consent = make_test_consent(
        from_date=datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc),
        to_date=datetime(2026, 10, 28, 0, 0, 0, tzinfo=timezone.utc),
    )
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(ConsentDateOutOfRangeError, match="fall outside the consented clinical date range"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_clinical_date_missing_timestamp_rejected():
    """Verify fail-closed rejection when an observation has missing effectiveDateTime."""
    bundle = make_test_bundle()
    for entry in bundle.entry:
        if hasattr(entry.resource, "resourceType") and entry.resource.resourceType == "Observation":
            entry.resource.effectiveDateTime = None

    consent = make_test_consent()
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(InvalidClinicalTimestampError, match="missing effectiveDateTime"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_clinical_date_unparseable_timestamp_rejected():
    """Verify fail-closed rejection when an observation has unparseable effectiveDateTime."""
    bundle = make_test_bundle()
    for entry in bundle.entry:
        if hasattr(entry.resource, "resourceType") and entry.resource.resourceType == "Observation":
            entry.resource.effectiveDateTime = "INVALID_CORRUPTED_DATE"

    consent = make_test_consent()
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    with pytest.raises(InvalidClinicalTimestampError, match="unparseable effectiveDateTime"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_bundle_preservation_zero_mutation():
    """Verify that the released bundle is strictly bit-for-bit identical to the input bundle."""
    bundle = make_test_bundle()
    original_dict = copy.deepcopy(bundle.model_dump(exclude_none=True))

    consent = make_test_consent()
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )
    resp = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)

    released_dict = resp.bundle.model_dump(exclude_none=True)
    assert released_dict == original_dict
    assert len(resp.bundle.entry) == len(bundle.entry)


# ============================================================================
# Section 7: Plain SHA-256 Integrity Digest & Audit Stability Tests
# ============================================================================

def test_integrity_digest_stable_and_deterministic():
    """Verify that evaluating the same bundle and consent yields a stable, deterministic SHA-256 digest."""
    bundle = make_test_bundle()
    consent = make_test_consent()
    req = GatewayReleaseRequest(
        consent=consent,
        bundle=bundle,
        hiu_id="HIU-TN-001",
        allow_test_signatures=True,
    )

    resp1 = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)
    resp2 = GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)

    assert resp1.integrity_digest == resp2.integrity_digest
    assert len(resp1.integrity_digest) == 64  # SHA-256 hex string


def test_integrity_digest_changes_on_bundle_tamper():
    """Verify that tampering with any bundle content changes the integrity digest."""
    bundle1 = make_test_bundle(observed_at="2026-10-27T10:15:00+00:00")
    bundle2 = copy.deepcopy(bundle1)

    for entry in bundle2.entry:
        if hasattr(entry.resource, "resourceType") and entry.resource.resourceType == "Observation":
            entry.resource.valueQuantity.value = 999.9  # modified result

    consent = make_test_consent()
    req1 = GatewayReleaseRequest(consent=consent, bundle=bundle1, hiu_id="HIU-TN-001", allow_test_signatures=True)
    req2 = GatewayReleaseRequest(consent=consent, bundle=bundle2, hiu_id="HIU-TN-001", allow_test_signatures=True)

    resp1 = GatewayService.evaluate_and_release(req1, evaluation_time=FIXED_NOW)
    resp2 = GatewayService.evaluate_and_release(req2, evaluation_time=FIXED_NOW)

    assert resp1.integrity_digest != resp2.integrity_digest


# ============================================================================
# Section 8: Bundle Structural Edge Cases
# ============================================================================

def test_bundle_empty_entries_rejected():
    """Verify that a bundle with empty entries raises InvalidGatewayRequestError."""
    bundle = make_test_bundle()
    bundle.entry = []
    consent = make_test_consent()
    req = GatewayReleaseRequest(consent=consent, bundle=bundle, hiu_id="HIU-TN-001", allow_test_signatures=True)

    with pytest.raises(InvalidGatewayRequestError, match="contains no entries"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_bundle_non_document_type_rejected():
    """Verify that non-document bundle raises InvalidGatewayRequestError."""
    bundle = make_test_bundle()
    bundle.type = "collection"  # type: ignore[assignment]
    consent = make_test_consent()
    req = GatewayReleaseRequest(consent=consent, bundle=bundle, hiu_id="HIU-TN-001", allow_test_signatures=True)

    with pytest.raises(InvalidGatewayRequestError, match="type must be 'document'"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_bundle_missing_patient_resource_rejected():
    """Verify that bundle lacking Patient resource raises InvalidGatewayRequestError."""
    bundle = make_test_bundle()
    bundle.entry = [e for e in bundle.entry if getattr(e.resource, "resourceType", None) != "Patient"]
    consent = make_test_consent()
    req = GatewayReleaseRequest(consent=consent, bundle=bundle, hiu_id="HIU-TN-001", allow_test_signatures=True)

    with pytest.raises(InvalidGatewayRequestError, match="must contain a Patient resource"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


def test_bundle_multiple_patient_resources_rejected():
    """Verify that bundle with multiple Patient resources raises InvalidGatewayRequestError."""
    bundle = make_test_bundle()
    pat_entry = [e for e in bundle.entry if getattr(e.resource, "resourceType", None) == "Patient"][0]
    bundle.entry.append(copy.deepcopy(pat_entry))

    consent = make_test_consent()
    req = GatewayReleaseRequest(consent=consent, bundle=bundle, hiu_id="HIU-TN-001", allow_test_signatures=True)

    with pytest.raises(InvalidGatewayRequestError, match="contains 2 Patient resources; ambiguous identity"):
        GatewayService.evaluate_and_release(req, evaluation_time=FIXED_NOW)


# ============================================================================
# Section 9: End-to-End API Route & Error Privacy Tests (SEC-M6-02)
# ============================================================================

def test_api_release_valid_request_200():
    """Verify successful 200 OK release response from POST /api/v1/gateway/release."""
    bundle = make_test_bundle()
    consent = make_test_consent()
    payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": json.loads(bundle.model_dump_json(exclude_none=True)),
        "hiu_id": "HIU-TN-001",
        "allow_test_signatures": True,
    }

    resp = client.post("/api/v1/gateway/release", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "released"
    assert data["consent_id"] == consent.consent_id
    assert data["hiu_id"] == "HIU-TN-001"
    assert data["hip_id"] == "PRV-GHT-01"
    assert data["patient_reference"] == "PT-2026-0091"
    assert data["observations_count"] == 1
    assert "integrity_digest" in data
    assert "bundle" in data
    assert data["bundle"]["resourceType"] == "Bundle"


def test_api_release_patient_mismatch_privacy_sanitized_403():
    """Verify 403 Forbidden on patient mismatch and confirm patient identifier is NOT leaked in message."""
    bundle = make_test_bundle(patient_id="PT-2026-0091")
    consent = make_test_consent(patient_id="PT-UNAUTHORIZED-99")
    payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": json.loads(bundle.model_dump_json(exclude_none=True)),
        "hiu_id": "HIU-TN-001",
        "allow_test_signatures": True,
    }

    resp = client.post("/api/v1/gateway/release", json=payload)
    assert resp.status_code == 403
    data = resp.json()
    assert data["error_code"] == "CONSENT_PATIENT_MISMATCH"
    # Strict privacy check: bundle's actual patient identifier must NOT be leaked
    assert "PT-2026-0091" not in resp.text
    assert data["message"] == "Patient identity in consent artefact does not match bundle subject."


def test_api_release_unauthorized_hiu_403():
    """Verify 403 Forbidden with error_code CONSENT_HIU_MISMATCH on unauthorized HIU."""
    bundle = make_test_bundle()
    consent = make_test_consent(hiu_id="HIU-TN-001")
    payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": json.loads(bundle.model_dump_json(exclude_none=True)),
        "hiu_id": "HIU-UNAUTHORIZED",
        "allow_test_signatures": True,
    }

    resp = client.post("/api/v1/gateway/release", json=payload)
    assert resp.status_code == 403
    data = resp.json()
    assert data["error_code"] == "CONSENT_HIU_MISMATCH"


def test_api_release_expired_consent_403():
    """Verify 403 Forbidden with error_code CONSENT_EXPIRED when consent has expired."""
    bundle = make_test_bundle()
    consent = make_test_consent(status="EXPIRED")
    payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": json.loads(bundle.model_dump_json(exclude_none=True)),
        "hiu_id": "HIU-TN-001",
        "allow_test_signatures": True,
    }

    resp = client.post("/api/v1/gateway/release", json=payload)
    assert resp.status_code == 403
    data = resp.json()
    assert data["error_code"] == "CONSENT_EXPIRED"


def test_api_release_revoked_consent_403():
    """Verify 403 Forbidden with error_code CONSENT_REVOKED when consent is revoked."""
    bundle = make_test_bundle()
    consent = make_test_consent(status="REVOKED")
    payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": json.loads(bundle.model_dump_json(exclude_none=True)),
        "hiu_id": "HIU-TN-001",
        "allow_test_signatures": True,
    }

    resp = client.post("/api/v1/gateway/release", json=payload)
    assert resp.status_code == 403
    data = resp.json()
    assert data["error_code"] == "CONSENT_REVOKED"


def test_api_release_date_out_of_range_privacy_sanitized_403():
    """Verify 403 on date out of range and confirm observation timestamp is NOT leaked in message."""
    bundle = make_test_bundle(observed_at="2026-10-27T10:15:00+00:00")
    consent = make_test_consent(
        from_date=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
        to_date=datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc),
    )
    payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": json.loads(bundle.model_dump_json(exclude_none=True)),
        "hiu_id": "HIU-TN-001",
        "allow_test_signatures": True,
    }

    resp = client.post("/api/v1/gateway/release", json=payload)
    assert resp.status_code == 403
    data = resp.json()
    assert data["error_code"] == "CONSENT_DATE_OUT_OF_RANGE"
    # Strict privacy check: clinical observation timestamp must NOT be leaked
    assert "2026-10-27" not in resp.text
    assert "10:15:00" not in resp.text


def test_api_release_missing_signature_without_server_permission_403(monkeypatch):
    """Verify 403 Forbidden when server disables test signatures even if caller supplies allow_test_signatures."""
    monkeypatch.setattr(settings, "ALLOW_TEST_SIGNATURES", False)
    bundle = make_test_bundle()
    consent = make_test_consent()
    payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": json.loads(bundle.model_dump_json(exclude_none=True)),
        "hiu_id": "HIU-TN-001",
        "allow_test_signatures": True,  # Attempt caller bypass
    }

    resp = client.post("/api/v1/gateway/release", json=payload)
    assert resp.status_code == 403
    data = resp.json()
    assert data["error_code"] == "INVALID_CONSENT_SIGNATURE"


def test_api_release_malformed_bundle_400():
    """Verify 400 Bad Request with error_code INVALID_GATEWAY_REQUEST on empty bundle entries."""
    bundle = make_test_bundle()
    bundle_dict = json.loads(bundle.model_dump_json(exclude_none=True))
    bundle_dict["entry"] = []

    consent = make_test_consent()
    payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": bundle_dict,
        "hiu_id": "HIU-TN-001",
        "allow_test_signatures": True,
    }

    resp = client.post("/api/v1/gateway/release", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["error_code"] == "INVALID_GATEWAY_REQUEST"


def test_api_health_endpoint_includes_m6():
    """Verify that GET /health lists M6_CONSENT_SECURITY_GATEWAY in its active modules."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "M6_CONSENT_SECURITY_GATEWAY" in data["modules"]
    assert "M5_FHIR_BUNDLE_ASSEMBLY" in data["modules"]


# ============================================================================
# Section 10: Full Multi-Module Pipeline Regression (M1 -> M2 -> M3 -> M5 -> M6)
# ============================================================================

def test_full_pipeline_m1_to_m6():
    """Verify seamless end-to-end flow from Ingestion (M1) to Secure Gateway Release (M6)."""
    # Step 1: M1 Ingest CSV
    csv_content = (
        "patient_id,test_name,result,unit,test_datetime,specimen\n"
        "PT-PIPELINE-01,Fasting Blood Glucose,105,mg/dL,2026-10-27T08:30:00Z,Serum\n"
    )
    m1_resp = client.post(
        "/api/v1/ingestion/csv",
        files={"file": ("lab_pipeline.csv", csv_content.encode("utf-8"), "text/csv")},
        headers={"X-Provider-ID": "HOSPITAL_A"},
    )
    assert m1_resp.status_code == 200
    m1_data = m1_resp.json()

    # Step 2: M2 Normalize
    m2_resp = client.post(
        "/api/v1/normalization/process",
        json=m1_data,
    )
    assert m2_resp.status_code == 200
    m2_data = m2_resp.json()

    # Step 3: M3 Terminology Map
    m3_resp = client.post(
        "/api/v1/terminology/map",
        json=m2_data,
    )
    assert m3_resp.status_code == 200
    m3_data = m3_resp.json()

    # Step 4: M5 Assemble FHIR Bundle
    m5_resp = client.post(
        "/api/v1/fhir/bundle",
        json={"batch": m3_data},
    )
    assert m5_resp.status_code == 200
    m5_data = m5_resp.json()
    assembled_bundle = m5_data["bundle"]

    # Step 5: M6 Secure Gateway Release
    consent = make_test_consent(
        patient_id="PT-PIPELINE-01",
        hip_id="HOSPITAL_A",
        hiu_id="HIU-TN-CITY-CLINIC",
        from_date=datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc),
        to_date=datetime(2026, 10, 28, 23, 59, 59, tzinfo=timezone.utc),
    )
    m6_payload = {
        "consent": json.loads(consent.model_dump_json()),
        "bundle": assembled_bundle,
        "hiu_id": "HIU-TN-CITY-CLINIC",
        "allow_test_signatures": True,
    }
    m6_resp = client.post("/api/v1/gateway/release", json=m6_payload)
    assert m6_resp.status_code == 200
    m6_data = m6_resp.json()

    assert m6_data["status"] == "released"
    assert m6_data["patient_reference"] == "PT-PIPELINE-01"
    assert m6_data["hip_id"] == "HOSPITAL_A"
    assert m6_data["hiu_id"] == "HIU-TN-CITY-CLINIC"
    assert m6_data["observations_count"] == 1
    assert m6_data["bundle"]["id"] == assembled_bundle["id"]
    assert len(m6_data["integrity_digest"]) == 64
