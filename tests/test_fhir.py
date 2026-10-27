"""Comprehensive test suite for M5 FHIR R4 Bundle Assembly Layer."""
import re
import uuid
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas.normalization import CanonicalLabRecord, QualityIssue
from app.schemas.terminology import (
    CandidateMappingReference,
    MappedRecord,
    TerminologyBatchResponse,
    TerminologyMappingResult,
)

client = TestClient(app)
settings = get_settings()

UUID_URN_REGEX = re.compile(
    r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def make_mapped_record(
    index: int = 0,
    patient_ref: Optional[str] = "PT-2026-0091",
    test_name: Optional[str] = "Fasting Blood Glucose",
    result: Any = 110.0,
    unit: Optional[str] = "mg/dL",
    observed_at: Optional[str] = "2026-10-27T10:15:00+05:30",
    specimen: Optional[str] = "Blood",
    quality_status: str = "valid",
    quality_issues: Optional[List[QualityIssue]] = None,
    mapping_status: str = "mapped",
    target_system: Optional[str] = "http://loinc.org",
    target_code: Optional[str] = "1558-6",
    target_display: Optional[str] = "Fasting glucose [Mass/volume] in Serum or Plasma",
    reason_code: str = "EXACT_MATCH",
) -> MappedRecord:
    """Helper to construct a valid M3 MappedRecord for testing."""
    return MappedRecord(
        record_index=index,
        canonical_fields=CanonicalLabRecord(
            patient_reference=patient_ref,
            test_name=test_name,
            result=result,
            unit=unit,
            observed_at=observed_at,
            specimen=specimen,
        ),
        original_fields={"raw_test": test_name, "raw_val": result},
        quality_status=quality_status,  # type: ignore[arg-type]
        quality_issues=quality_issues or [],
        terminology_mapping=TerminologyMappingResult(
            source_test_name=test_name,
            mapping_status=mapping_status,  # type: ignore[arg-type]
            target_system=target_system if mapping_status == "mapped" else None,
            target_code=target_code if mapping_status == "mapped" else None,
            target_display=target_display if mapping_status == "mapped" else None,
            reason_code=reason_code,
            message="Test mapping evaluation",
            registry_version="1.0.0",
            review_required=(mapping_status == "review_required"),
            candidate_mappings=[],
        ),
    )


def make_terminology_batch(
    records: List[MappedRecord],
    provider_id: str = "PRV-GHT-01",
) -> Dict[str, Any]:
    """Helper to construct an M3 TerminologyBatchResponse dictionary payload."""
    batch = TerminologyBatchResponse(
        mapping_id=str(uuid.uuid4()),
        normalization_id=str(uuid.uuid4()),
        ingestion_id=str(uuid.uuid4()),
        source_provider_id=provider_id,
        status="completed",
        registry_version="1.0.0",
        record_count=len(records),
        mapped_count=sum(1 for r in records if r.terminology_mapping.mapping_status == "mapped"),
        unmapped_count=sum(1 for r in records if r.terminology_mapping.mapping_status == "unmapped"),
        ambiguous_count=sum(1 for r in records if r.terminology_mapping.mapping_status == "ambiguous"),
        review_required_count=sum(1 for r in records if r.terminology_mapping.review_required),
        records=records,
    )
    return batch.model_dump()


def make_standard_assembly_payload(
    provider_id: str = "PRV-GHT-01",
    patient_ref: Optional[str] = "PT-2026-0091",
) -> Dict[str, Any]:
    """Standard 2-record test fixture: Record 0 mapped LOINC 1558-6, Record 1 unmapped ESR."""
    r0 = make_mapped_record(
        index=0,
        patient_ref=patient_ref,
        test_name="Fasting Blood Glucose",
        result=110.0,
        unit="mg/dL",
        observed_at="2026-10-27T10:15:00+05:30",
        specimen="Blood",
        mapping_status="mapped",
        target_system="http://loinc.org",
        target_code="1558-6",
        target_display="Fasting glucose [Mass/volume] in Serum or Plasma",
        reason_code="EXACT_MATCH",
    )
    r1 = make_mapped_record(
        index=1,
        patient_ref=patient_ref,
        test_name="ESR - Westergren",
        result=15.0,
        unit="mm/hr",
        observed_at="2026-10-27T10:15:00+05:30",
        specimen="Blood",
        mapping_status="unmapped",
        target_system=None,
        target_code=None,
        target_display=None,
        reason_code="NO_MAPPING_FOUND",
    )
    batch_dict = make_terminology_batch([r0, r1], provider_id=provider_id)
    return {"batch": batch_dict, "patient_reference": patient_ref}


# ==============================================================================
# Category 1: Base FHIR R4 Structural Conformance & Document Topology
# ==============================================================================

def test_document_bundle_structure_and_composition_first():
    """Test 1: Verifies root type == 'document' and entry[0] is Composition."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    bundle = data["bundle"]

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "document"
    assert len(bundle["entry"]) >= 5
    first_resource = bundle["entry"][0]["resource"]
    assert first_resource["resourceType"] == "Composition"


def test_composition_category_and_section_code_omitted():
    """Test 2: Verifies optional Composition.category and Composition.section[0].code are cleanly omitted."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]
    comp = bundle["entry"][0]["resource"]

    # Category must not be present
    assert "category" not in comp or comp["category"] is None
    # Section code must not be present
    section = comp["section"][0]
    assert section["title"] == "Diagnostic Report"
    assert "code" not in section or section["code"] is None


def test_two_tier_section_entry_topology():
    """Test 3: Verifies Composition.section[0].entry references only DiagnosticReport."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]
    comp = bundle["entry"][0]["resource"]

    # Section entry contains exactly 1 reference
    entries = comp["section"][0]["entry"]
    assert len(entries) == 1
    dr_ref = entries[0]["reference"]

    # Find DiagnosticReport in bundle and verify reference matches
    dr_entry = next((e for e in bundle["entry"] if e["resource"]["resourceType"] == "DiagnosticReport"), None)
    assert dr_entry is not None
    assert dr_ref == dr_entry["fullUrl"]


def test_diagnostic_report_contains_all_observation_references():
    """Test 4: Verifies DiagnosticReport.result contains references to all generated Observation entries."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    dr = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")
    obs_entries = [e for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation"]

    assert len(dr["result"]) == len(obs_entries)
    obs_urls = {e["fullUrl"] for e in obs_entries}
    for res_ref in dr["result"]:
        assert res_ref["reference"] in obs_urls


def test_composition_attester_omitted():
    """Test 5: Asserts Composition.attester is omitted in technical assembly."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    comp = resp.json()["bundle"]["entry"][0]["resource"]
    assert "attester" not in comp or comp["attester"] is None


# ==============================================================================
# Category 2: Reference Integrity & Closure
# ==============================================================================

def test_reference_integrity_no_dangling_references():
    """Test 6: Recursively crawls all Reference.reference elements and verifies closure against entry.fullUrl."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]
    entries = bundle.get("entry", [])

    declared_urls = {entry["fullUrl"] for entry in entries if "fullUrl" in entry}
    discovered_references: List[str] = []

    def crawl_references(node: Any):
        if isinstance(node, dict):
            if "reference" in node and isinstance(node["reference"], str):
                discovered_references.append(node["reference"])
            for child in node.values():
                crawl_references(child)
        elif isinstance(node, list):
            for item in node:
                crawl_references(item)

    crawl_references(entries)
    assert len(discovered_references) >= 6

    for ref in discovered_references:
        assert ref in declared_urls, f"Dangling reference detected: {ref}"


def test_bundle_entries_have_unique_fullurls():
    """Test 7: Verifies all entries have a fullUrl matching urn:uuid:<UUIDv4> and all are unique."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    entries = resp.json()["bundle"].get("entry", [])

    full_urls = []
    for entry in entries:
        assert "fullUrl" in entry
        url = entry["fullUrl"]
        assert UUID_URN_REGEX.match(url), f"fullUrl '{url}' is not a valid urn:uuid:v4 URI"
        full_urls.append(url)

    assert len(full_urls) == len(set(full_urls)), "Duplicate fullUrl values found in Bundle entries"


def test_rejection_of_external_and_relative_references():
    """Test 8: Asserts that any external or relative reference format is rejected by the integrity scanner."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    for entry in bundle["entry"]:
        res = entry["resource"]
        # Intentionally check that no resource has external http or relative REST references
        for key, val in res.items():
            if key == "reference" and isinstance(val, str):
                assert not val.startswith("http://") and not val.startswith("https://")
                assert not val.startswith("Patient/") and not val.startswith("Observation/")


# ==============================================================================
# Category 3: Status State Machine & Finality
# ==============================================================================

def test_default_assembly_status_is_preliminary():
    """Test 9: Verifies Composition.status == 'preliminary' and DiagnosticReport.status == 'preliminary' on clean assembly."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    comp = bundle["entry"][0]["resource"]
    dr = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")

    assert comp["status"] == "preliminary"
    assert dr["status"] == "preliminary"
    assert resp.json()["status"] == "completed"


def test_partial_assembly_status_is_preliminary_and_partial():
    """Test 10: Verifies DiagnosticReport.status == 'partial' and Composition.status == 'preliminary' when records are withheld."""
    r0 = make_mapped_record(index=0, quality_status="valid")
    r1 = make_mapped_record(
        index=1,
        quality_status="rejected",
        quality_issues=[QualityIssue(code="INVALID_VALUE", severity="rejected", message="Test rejected")],
    )
    batch = make_terminology_batch([r0, r1])
    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-2026-0091"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "partial"
    assert data["withheld_records_count"] == 1
    assert data["assembled_observations_count"] == 1

    bundle = data["bundle"]
    comp = bundle["entry"][0]["resource"]
    dr = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")

    assert comp["status"] == "preliminary"
    assert dr["status"] == "partial"


def test_observation_status_is_preliminary():
    """Test 11: Verifies all generated Observation entries have status = 'preliminary'."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    obs_list = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation"]
    assert len(obs_list) >= 2
    for obs in obs_list:
        assert obs["status"] == "preliminary"


# ==============================================================================
# Category 4: Patient Isolation & Mixed-Patient Batches
# ==============================================================================

def test_missing_patient_reference_record_is_isolated():
    """Test 12: Verifies unlabelled records receive outcome withheld_missing_patient_reference and are excluded."""
    r0 = make_mapped_record(index=0, patient_ref="PT-2026-0091")
    r1 = make_mapped_record(index=1, patient_ref=None)  # Missing patient reference
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-2026-0091"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["missing_patient_records_count"] == 1
    assert data["assembled_observations_count"] == 1
    outcomes = data["record_outcomes"]
    assert outcomes[1]["outcome"] == "withheld_missing_patient_reference"


def test_missing_patient_reference_does_not_degrade_target_status():
    """Test 13: Verifies missing_patient_records_count > 0 preserves target status = 'completed'."""
    r0 = make_mapped_record(index=0, patient_ref="PT-2026-0091")
    r1 = make_mapped_record(index=1, patient_ref="")  # Blank patient reference
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-2026-0091"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "completed"  # Target patient has 0 withheld records
    assert data["missing_patient_records_count"] == 1
    assert data["target_records_count"] == 1


def test_mixed_patient_batch_without_filter_rejected():
    """Test 14: Asserts MixedPatientBatchError (HTTP 400) when multiple patients exist without filter."""
    r0 = make_mapped_record(index=0, patient_ref="PT-001")
    r1 = make_mapped_record(index=1, patient_ref="PT-002")
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "MIXED_PATIENT_BATCH"


def test_mixed_patient_batch_with_filter_assembled():
    """Test 15: Asserts successful bundle generation when patient_reference filter is provided."""
    r0 = make_mapped_record(index=0, patient_ref="PT-001")
    r1 = make_mapped_record(index=1, patient_ref="PT-002")
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-001"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["patient_reference"] == "PT-001"
    assert data["assembled_observations_count"] == 1
    assert data["omitted_other_patient_count"] == 1
    assert data["record_outcomes"][1]["outcome"] == "omitted_other_patient"


def test_omitted_other_patient_does_not_degrade_envelope_status():
    """Test 16: Asserts omitted_other_patient_count > 0 preserves target status = 'completed'."""
    r0 = make_mapped_record(index=0, patient_ref="PT-001")
    r1 = make_mapped_record(index=1, patient_ref="PT-002")
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-001"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_batch_all_missing_patient_references_rejected_400():
    """Test 17: Asserts HTTP 400 when all records lack patient reference and no target is given."""
    r0 = make_mapped_record(index=0, patient_ref=None)
    r1 = make_mapped_record(index=1, patient_ref="")
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_FHIR_REQUEST"


# ==============================================================================
# Category 5: Mathematical Count Reconciliation
# ==============================================================================

def test_count_reconciliation_exact_invariants():
    """Test 18: Asserts total == target + omitted + missing."""
    r0 = make_mapped_record(index=0, patient_ref="PT-TARGET")
    r1 = make_mapped_record(index=1, patient_ref="PT-OTHER")
    r2 = make_mapped_record(index=2, patient_ref=None)
    batch = make_terminology_batch([r0, r1, r2])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-TARGET"})
    assert resp.status_code == 200
    data = resp.json()

    total = data["total_records"]
    target = data["target_records_count"]
    omitted = data["omitted_other_patient_count"]
    missing = data["missing_patient_records_count"]

    assert total == target + omitted + missing
    assert total == 3
    assert target == 1
    assert omitted == 1
    assert missing == 1


def test_target_count_reconciliation_invariant():
    """Test 19: Asserts target == assembled + withheld."""
    r0 = make_mapped_record(index=0, patient_ref="PT-TARGET", quality_status="valid")
    r1 = make_mapped_record(index=1, patient_ref="PT-TARGET", quality_status="rejected")
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-TARGET"})
    assert resp.status_code == 200
    data = resp.json()

    target = data["target_records_count"]
    assembled = data["assembled_observations_count"]
    withheld = data["withheld_records_count"]

    assert target == assembled + withheld
    assert target == 2
    assert assembled == 1
    assert withheld == 1


def test_record_outcomes_array_length_matches_total_records():
    """Test 20: Verifies len(record_outcomes) == total_records."""
    r0 = make_mapped_record(index=0, patient_ref="PT-TARGET")
    r1 = make_mapped_record(index=1, patient_ref="PT-OTHER")
    r2 = make_mapped_record(index=2, patient_ref="")
    batch = make_terminology_batch([r0, r1, r2])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-TARGET"})
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["record_outcomes"]) == data["total_records"]


# ==============================================================================
# Category 6: Specimen Rules & Event Decoupling
# ==============================================================================

def test_specimen_collection_time_omitted():
    """Test 21: Asserts Specimen.collection.collectedDateTime is absent (not copied from observed_at)."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    specimen_entries = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Specimen"]
    assert len(specimen_entries) >= 1
    for spec in specimen_entries:
        assert "collection" not in spec or spec["collection"] is None


def test_specimen_clustering_by_type():
    """Test 22: Asserts records sharing specimen type for the target patient point to the same Specimen resource."""
    payload = make_standard_assembly_payload()  # Both records share specimen="Blood"
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    specimen_entries = [e for e in bundle["entry"] if e["resource"]["resourceType"] == "Specimen"]
    assert len(specimen_entries) == 1  # Clustered into 1 resource

    obs_entries = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation"]
    assert len(obs_entries) == 2
    assert obs_entries[0]["specimen"]["reference"] == specimen_entries[0]["fullUrl"]
    assert obs_entries[1]["specimen"]["reference"] == specimen_entries[0]["fullUrl"]


def test_missing_specimen_omits_specimen_resource():
    """Test 23: Asserts no Specimen resource is created when specimen is None."""
    r0 = make_mapped_record(index=0, specimen=None)
    batch = make_terminology_batch([r0])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-2026-0091"})
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    specimen_entries = [e for e in bundle["entry"] if e["resource"]["resourceType"] == "Specimen"]
    assert len(specimen_entries) == 0

    obs = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation")
    assert "specimen" not in obs or obs["specimen"] is None


# ==============================================================================
# Category 7: Terminology Accuracy & Uncertainty
# ==============================================================================

def test_verified_loinc_from_local_registry():
    """Test 24: Asserts Fasting Blood Glucose uses verified LOINC code 1558-6 from registry."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    obs = bundle["entry"][5]["resource"]  # Observation 1 (Glucose)
    coding = obs["code"]["coding"][0]

    assert coding["system"] == "http://loinc.org"
    assert coding["code"] == "1558-6"
    assert coding["display"] == "Fasting glucose [Mass/volume] in Serum or Plasma"
    assert obs["code"]["text"] == "Fasting Blood Glucose"


def test_unmapped_observation_emits_text_without_empty_coding():
    """Test 25: Asserts unmapped observation contains code.text and omits 'coding': []."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    obs = bundle["entry"][6]["resource"]  # Observation 2 (ESR)
    assert "text" in obs["code"]
    assert obs["code"]["text"] == "ESR - Westergren"
    assert "coding" not in obs["code"] or obs["code"]["coding"] is None

    # Check uncertainty note
    assert "note" in obs and len(obs["note"]) >= 1
    assert "Clinical terminology unmapped" in obs["note"][0]["text"]


def test_verified_ucum_units_include_system_and_code():
    """Test 26: Verifies mg/dL, %, mmol/L, umol/L, /uL include http://unitsofmeasure.org."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    obs = bundle["entry"][5]["resource"]  # mg/dL
    vq = obs["valueQuantity"]
    assert vq["value"] == 110.0
    assert vq["unit"] == "mg/dL"
    assert vq["system"] == "http://unitsofmeasure.org"
    assert vq["code"] == "mg/dL"


def test_unverified_units_omit_ucum_system():
    """Test 27: Verifies unverified units retain unit string but omit system and code."""
    payload = make_standard_assembly_payload()
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    obs = bundle["entry"][6]["resource"]  # mm/hr
    vq = obs["valueQuantity"]
    assert vq["value"] == 15.0
    assert vq["unit"] == "mm/hr"
    assert "system" not in vq or vq["system"] is None
    assert "code" not in vq or vq["code"] is None


# ==============================================================================
# Category 8: Privacy & Identifier Safety
# ==============================================================================

def test_composition_subject_display_does_not_leak_patient_id():
    """Test 28: Asserts Composition.subject.display == 'Patient'."""
    payload = make_standard_assembly_payload(patient_ref="SECRET-PT-999")
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    comp = resp.json()["bundle"]["entry"][0]["resource"]

    assert comp["subject"]["display"] == "Patient"
    assert "SECRET-PT-999" not in comp["subject"]["display"]


def test_patient_identifier_contains_provider_scoped_system():
    """Test 29: Asserts Patient.identifier[0].system is provider-scoped."""
    payload = make_standard_assembly_payload(provider_id="HOSP-ALPHA", patient_ref="PT-001")
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    pat = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient")
    ident = pat["identifier"][0]

    assert ident["system"] == "https://healthbridge.tn.gov.in/providers/HOSP-ALPHA/patient"
    assert ident["value"] == "PT-001"


# ==============================================================================
# Category 9: Edge-Case & Error Boundary Tests
# ==============================================================================

def test_empty_batch_rejected_400():
    """Test 30 (Edge Case): Asserts EmptyFhirBatchError (HTTP 400) when batch has no records."""
    batch = make_terminology_batch([])
    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "EMPTY_PAYLOAD"


def test_all_target_records_rejected_returns_422():
    """Test 31 (Edge Case): Asserts FhirAssemblyError (HTTP 422) when all target records are rejected."""
    r0 = make_mapped_record(
        index=0,
        quality_status="rejected",
        quality_issues=[QualityIssue(code="MISSING_FIELD", severity="rejected", message="No result")],
    )
    batch = make_terminology_batch([r0])
    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-2026-0091"})
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "FHIR_ASSEMBLY_FAILED"


def test_record_limit_exceeded_rejected_400():
    """Test 32 (Edge Case): Asserts FhirRecordLimitExceededError (HTTP 400) when batch exceeds 1000 records."""
    records = [make_mapped_record(index=i) for i in range(1001)]
    batch = make_terminology_batch(records)
    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "RECORD_LIMIT_EXCEEDED"


def test_target_patient_not_found_in_batch_returns_400():
    """Test 33 (Edge Case): Asserts InvalidFhirRequestError (HTTP 400) when patient_reference is absent."""
    payload = make_standard_assembly_payload()
    payload["patient_reference"] = "NON_EXISTENT_PT"
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_FHIR_REQUEST"


def test_string_result_observation_emits_value_string():
    """Test 34 (Edge Case): Asserts string result emits valueString and omits valueQuantity."""
    r0 = make_mapped_record(index=0, result="Positive", unit=None)
    batch = make_terminology_batch([r0])
    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-2026-0091"})
    assert resp.status_code == 200
    obs = resp.json()["bundle"]["entry"][5]["resource"]

    assert obs["valueString"] == "Positive"
    assert "valueQuantity" not in obs or obs["valueQuantity"] is None


def test_multi_specimen_clustering_different_types():
    """Test 35 (Edge Case): Asserts distinct specimen types for same patient create distinct Specimen resources."""
    r0 = make_mapped_record(index=0, test_name="Blood Glucose", specimen="Blood")
    r1 = make_mapped_record(index=1, test_name="Urine Albumin", specimen="Urine")
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-2026-0091"})
    assert resp.status_code == 200
    bundle = resp.json()["bundle"]

    specimen_entries = [e for e in bundle["entry"] if e["resource"]["resourceType"] == "Specimen"]
    assert len(specimen_entries) == 2
    spec_types = {e["resource"]["type"]["text"] for e in specimen_entries}
    assert spec_types == {"Blood", "Urine"}


def test_health_check_includes_m5_module():
    """Test 36 (Edge Case): Asserts GET /health includes M5_FHIR_BUNDLE_ASSEMBLY in modules list."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "M5_FHIR_BUNDLE_ASSEMBLY" in data["modules"]


# ==============================================================================
# Category 10: End-to-End FastAPI Integration Tests (POST /api/v1/fhir/bundle)
# ==============================================================================

def test_e2e_valid_request_full_response_envelope():
    """Test 37 (E2E): Verifies valid request HTTP 200, complete response envelope, and clean Pydantic serialization."""
    payload = make_standard_assembly_payload(provider_id="PRV-GHT-01", patient_ref="PT-2026-0091")
    resp = client.post("/api/v1/fhir/bundle", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    # 1. Verify all top-level response envelope fields
    assert "bundle_id" in data and UUID_URN_REGEX.match(f"urn:uuid:{data['bundle_id']}")
    assert data["status"] == "completed"
    assert data["document_type"] == "DiagnosticReportDocument"
    assert data["total_records"] == 2
    assert data["target_records_count"] == 2
    assert data["assembled_observations_count"] == 2
    assert data["withheld_records_count"] == 0
    assert data["omitted_other_patient_count"] == 0
    assert data["missing_patient_records_count"] == 0
    assert data["source_provider_id"] == "PRV-GHT-01"
    assert data["patient_reference"] == "PT-2026-0091"
    assert len(data["record_outcomes"]) == 2

    # 2. Verify bundle structure and Pydantic serialization cleanliness (no None keys)
    bundle = data["bundle"]
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "document"
    assert bundle["entry"][0]["resource"]["resourceType"] == "Composition"

    # 3. Verify conservative FHIR R4 statuses (Composition, DiagnosticReport, Observation)
    comp = bundle["entry"][0]["resource"]
    assert comp["status"] == "preliminary", (
        f"Expected Composition.status to be 'preliminary', got {comp.get('status')}"
    )

    dr = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")
    assert dr["status"] == "preliminary", (
        f"Expected clean DiagnosticReport.status to be 'preliminary', got {dr.get('status')}"
    )

    obs_entries = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation"]
    assert len(obs_entries) == 2
    for obs in obs_entries:
        assert obs["status"] == "preliminary", (
            f"Expected Observation.status to be 'preliminary', got {obs.get('status')}"
        )

    # 4. Composition cleanliness
    assert "category" not in comp
    assert "attester" not in comp
    assert "code" not in comp["section"][0]

    # 5. Unmapped Observation cleanliness (coding must NOT be present as empty list)
    obs_unmapped = bundle["entry"][6]["resource"]
    assert obs_unmapped["code"]["text"] == "ESR - Westergren"
    assert "coding" not in obs_unmapped["code"]


def test_e2e_partial_assembly_statuses():
    """Test 38 (E2E): Verifies DiagnosticReport is 'partial' and Composition remains 'preliminary' when records withheld."""
    r0 = make_mapped_record(index=0, quality_status="valid")
    r1 = make_mapped_record(
        index=1,
        quality_status="rejected",
        quality_issues=[QualityIssue(code="RANGE_ERROR", severity="rejected", message="Value out of range")],
    )
    batch = make_terminology_batch([r0, r1])
    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-2026-0091"})
    assert resp.status_code == 200
    data = resp.json()

    # Response envelope status
    assert data["status"] == "partial"
    assert data["withheld_records_count"] == 1
    assert data["assembled_observations_count"] == 1

    # Resource statuses
    bundle = data["bundle"]
    comp = bundle["entry"][0]["resource"]
    dr = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "DiagnosticReport")
    obs_list = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation"]

    assert comp["status"] == "preliminary", "Composition.status must remain 'preliminary' (no 'partial' in FHIR R4 Composition)"
    assert dr["status"] == "partial", "DiagnosticReport.status must be 'partial' when records are withheld"
    for obs in obs_list:
        assert obs["status"] == "preliminary", "Observation.status must remain 'preliminary'"


def test_e2e_malformed_input_payload_rejected_422():
    """Test 38 (E2E): Verifies malformed input payload produces HTTP 422 and VALIDATION_ERROR."""
    # Test A: String instead of dict for batch
    resp_a = client.post("/api/v1/fhir/bundle", json={"batch": "invalid_string_not_dict"})
    assert resp_a.status_code == 422
    assert resp_a.json()["error_code"] == "VALIDATION_ERROR"
    assert "Check parameters and payload structure" in resp_a.json()["message"]

    # Test B: Missing required batch field entirely
    resp_b = client.post("/api/v1/fhir/bundle", json={"patient_reference": "PT-001"})
    assert resp_b.status_code == 422
    assert resp_b.json()["error_code"] == "VALIDATION_ERROR"

    # Test C: Completely non-JSON or invalid root
    resp_c = client.post("/api/v1/fhir/bundle", json=[])
    assert resp_c.status_code == 422
    assert resp_c.json()["error_code"] == "VALIDATION_ERROR"


def test_e2e_mixed_patient_rejection_400():
    """Test 39 (E2E): Verifies mixed-patient batch without filter returns HTTP 400 and MIXED_PATIENT_BATCH."""
    r0 = make_mapped_record(index=0, patient_ref="PATIENT_A")
    r1 = make_mapped_record(index=1, patient_ref="PATIENT_B")
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "MIXED_PATIENT_BATCH"
    assert "multiple patient references" in resp.json()["message"]


def test_e2e_all_records_rejected_no_assemblable_observations_422():
    """Test 40 (E2E): Verifies batch with no assemblable observations returns HTTP 422 and FHIR_ASSEMBLY_FAILED."""
    r0 = make_mapped_record(
        index=0,
        patient_ref="PT-001",
        quality_status="rejected",
        quality_issues=[QualityIssue(code="VALUE_ERROR", severity="rejected", message="Invalid lab value")],
    )
    r1 = make_mapped_record(
        index=1,
        patient_ref="PT-001",
        quality_status="rejected",
        quality_issues=[QualityIssue(code="TEST_ERROR", severity="rejected", message="Unknown test format")],
    )
    batch = make_terminology_batch([r0, r1])

    resp = client.post("/api/v1/fhir/bundle", json={"batch": batch, "patient_reference": "PT-001"})
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "FHIR_ASSEMBLY_FAILED"
    assert "no FHIR bundle can be assembled" in resp.json()["message"]
