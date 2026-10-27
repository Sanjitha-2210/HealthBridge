"""Service implementation for M5 FHIR R4 Bundle Assembly."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from app.core.errors import (
    EmptyFhirBatchError,
    FhirAssemblyError,
    FhirRecordLimitExceededError,
    InvalidFhirRequestError,
    MixedPatientBatchError,
)
from app.schemas.fhir import (
    Annotation,
    Bundle,
    BundleEntry,
    CodeableConcept,
    Coding,
    Composition,
    CompositionSection,
    DiagnosticReport,
    FhirBundleAssemblyRequest,
    FhirBundleAssemblyResponse,
    Identifier,
    Observation,
    Organization,
    Patient,
    Quantity,
    RecordAssemblyOutcome,
    RecordOutcomeType,
    Reference,
    Specimen,
    SpecimenType,
)
from app.schemas.terminology import MappedRecord

logger = logging.getLogger("tn_healthbridge.fhir_service")

# Standard verified UCUM units with unambiguous clinical mappings
VERIFIED_UCUM_UNITS: Set[str] = {"mg/dL", "%", "mmol/L", "umol/L", "/uL"}
MAX_BATCH_RECORDS: int = 1000

# Canonical LOINC and Terminology System URIs
LOINC_SYSTEM = "http://loinc.org"
LOINC_LAB_REPORT_CODE = "11502-2"
LOINC_LAB_REPORT_DISPLAY = "Laboratory report"
HL7_DIAGNOSTIC_SERVICE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0074"
HL7_OBSERVATION_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
UCUM_SYSTEM = "http://unitsofmeasure.org"


class FhirService:
    """Zero-persistence, uncertainty-aware FHIR R4 Document Bundle assembly service."""

    @staticmethod
    def assemble_bundle(request: FhirBundleAssemblyRequest) -> FhirBundleAssemblyResponse:
        """Assemble an uncertainty-aware FHIR R4 Document Bundle from an M3 terminology batch.
        
        Enforces:
        - Strict document bundle topology with Composition as entry[0].
        - Two-tier section entry hierarchy (Composition -> DiagnosticReport -> Observation).
        - Patient isolation and mixed-patient safety (no cross-patient contamination).
        - Conservative preliminary status assignment and partial report tracking.
        - Verified LOINC mapping vs unmapped text-only preservation.
        - Closed internal reference resolution with unique urn:uuid: URIs.
        """
        records: List[MappedRecord] = request.batch.records

        # 1. Input Batch Size Validations
        if not records:
            raise EmptyFhirBatchError("FHIR bundle assembly batch contains no records.")

        if len(records) > MAX_BATCH_RECORDS:
            raise FhirRecordLimitExceededError(
                record_count=len(records),
                max_records=MAX_BATCH_RECORDS,
            )

        # 2. Patient Isolation and Target Patient Resolution
        distinct_patients: Set[str] = set()
        has_missing_patient: bool = False

        for r in records:
            p_ref = r.canonical_fields.patient_reference
            if p_ref and p_ref.strip():
                distinct_patients.add(p_ref.strip())
            else:
                has_missing_patient = True

        if request.patient_reference is not None and request.patient_reference.strip():
            target_pt: str = request.patient_reference.strip()
            if target_pt not in distinct_patients:
                raise InvalidFhirRequestError(
                    f"Requested patient_reference '{target_pt}' does not match any record in the batch."
                )
        else:
            # No explicit filter supplied -> Single-patient batch validation
            if len(distinct_patients) == 0:
                raise InvalidFhirRequestError(
                    "Cannot assemble FHIR document: all records in batch lack patient_reference."
                )
            if has_missing_patient:
                raise MixedPatientBatchError(
                    "Batch contains records with missing patient references alongside identified patients; "
                    "explicit patient_reference is required."
                )
            if len(distinct_patients) > 1:
                raise MixedPatientBatchError(
                    f"Batch contains multiple patient references ({len(distinct_patients)}); "
                    "explicit patient_reference is required."
                )
            target_pt = next(iter(distinct_patients))

        # 3. Categorize Records and Collect Assembly Outcomes
        total_records: int = len(records)
        record_outcomes: List[RecordAssemblyOutcome] = []
        target_records: List[MappedRecord] = []
        omitted_other_patient_count: int = 0
        missing_patient_records_count: int = 0

        for r in records:
            p_ref = r.canonical_fields.patient_reference
            clean_ref = p_ref.strip() if p_ref and p_ref.strip() else None

            if clean_ref is None:
                missing_patient_records_count += 1
                record_outcomes.append(
                    RecordAssemblyOutcome(
                        record_index=r.record_index,
                        outcome="withheld_missing_patient_reference",
                        reason_code="MISSING_PATIENT_REFERENCE",
                        message="Record missing patient_reference; excluded to prevent unverified patient attribution.",
                    )
                )
            elif clean_ref != target_pt:
                omitted_other_patient_count += 1
                record_outcomes.append(
                    RecordAssemblyOutcome(
                        record_index=r.record_index,
                        outcome="omitted_other_patient",
                        reason_code="PATIENT_FILTER_EXCLUSION",
                        message=f"Record belongs to patient {clean_ref}; excluded from document for {target_pt}.",
                    )
                )
            else:
                # Belongs to target patient
                target_records.append(r)
                if r.quality_status == "rejected":
                    issue_msg = (
                        "; ".join(q.message for q in r.quality_issues)
                        if r.quality_issues
                        else "Upstream data quality rejection"
                    )
                    record_outcomes.append(
                        RecordAssemblyOutcome(
                            record_index=r.record_index,
                            outcome="withheld_quality_rejection",
                            reason_code="UPSTREAM_QUALITY_REJECTION",
                            message=f"Record withheld from FHIR assembly due to M2 quality rejection: {issue_msg}",
                        )
                    )
                else:
                    # Valid or Warning
                    if (
                        r.terminology_mapping.mapping_status == "mapped"
                        and r.terminology_mapping.target_code
                    ):
                        record_outcomes.append(
                            RecordAssemblyOutcome(
                                record_index=r.record_index,
                                outcome="assembled_loinc_mapped",
                                reason_code=r.terminology_mapping.reason_code or "EXACT_MATCH",
                                message=f"Observation assembled with standard concept {r.terminology_mapping.target_code}.",
                            )
                        )
                    else:
                        record_outcomes.append(
                            RecordAssemblyOutcome(
                                record_index=r.record_index,
                                outcome="assembled_text_only_unmapped",
                                reason_code=r.terminology_mapping.reason_code or "NO_MAPPING_FOUND",
                                message=(
                                    "Observation assembled with source investigation text. "
                                    f"Standard coding omitted due to terminology status '{r.terminology_mapping.mapping_status}'."
                                ),
                            )
                        )

        # 4. Count Invariants & Rejection Gate
        target_records_count: int = len(target_records)
        withheld_records_count: int = sum(
            1 for o in record_outcomes if o.outcome == "withheld_quality_rejection"
        )
        valid_target_records: List[MappedRecord] = [
            r for r in target_records if r.quality_status != "rejected"
        ]
        assembled_observations_count: int = len(valid_target_records)

        # Invariant Assertions
        assert total_records == (
            target_records_count + omitted_other_patient_count + missing_patient_records_count
        ), "Count invariant violated: total != target + omitted + missing"
        assert target_records_count == (
            assembled_observations_count + withheld_records_count
        ), "Count invariant violated: target != assembled + withheld"
        assert len(record_outcomes) == total_records, (
            "Count invariant violated: record_outcomes length mismatch"
        )

        if assembled_observations_count == 0:
            raise FhirAssemblyError(
                "All records for target patient were withheld due to quality rejection; "
                "no FHIR bundle can be assembled."
            )

        # 5. Resource Generation & Random UUIDv4 Allocation (independent of patient identity)
        bundle_id: str = str(uuid.uuid4())
        comp_id: str = str(uuid.uuid4())
        pat_id: str = str(uuid.uuid4())
        org_id: str = str(uuid.uuid4())
        dr_id: str = str(uuid.uuid4())
        current_timestamp: str = datetime.now(timezone.utc).isoformat()

        # Build Patient (Provider-scoped system URI)
        patient_resource = Patient(
            id=pat_id,
            identifier=[
                Identifier(
                    system=f"https://healthbridge.tn.gov.in/providers/{request.batch.source_provider_id}/patient",
                    value=target_pt,
                )
            ],
            active=True,
        )

        # Build Organization
        organization_resource = Organization(
            id=org_id,
            identifier=[
                Identifier(
                    system="https://healthbridge.tn.gov.in/providers",
                    value=request.batch.source_provider_id,
                )
            ],
            name=request.batch.source_provider_id,
        )

        # Specimen Clustering: group by normalized specimen string; omit draw timestamp
        specimen_map: Dict[str, Tuple[str, Specimen]] = {}
        for r in valid_target_records:
            raw_spec = r.canonical_fields.specimen
            if raw_spec and raw_spec.strip():
                clean_spec = raw_spec.strip()
                if clean_spec not in specimen_map:
                    spec_id = str(uuid.uuid4())
                    spec_res = Specimen(
                        id=spec_id,
                        type=SpecimenType(text=clean_spec),
                        subject=Reference(reference=f"urn:uuid:{pat_id}"),
                    )
                    specimen_map[clean_spec] = (spec_id, spec_res)

        # Build Observation Resources
        observation_entries: List[Tuple[str, Observation]] = []
        for r in valid_target_records:
            obs_id = str(uuid.uuid4())

            # Terminology Mapping & Text-Only Fallback
            if (
                r.terminology_mapping.mapping_status == "mapped"
                and r.terminology_mapping.target_code
            ):
                code_elem = CodeableConcept(
                    coding=[
                        Coding(
                            system=r.terminology_mapping.target_system or LOINC_SYSTEM,
                            code=r.terminology_mapping.target_code,
                            display=r.terminology_mapping.target_display,
                        )
                    ],
                    text=(
                        r.canonical_fields.test_name
                        or r.terminology_mapping.source_test_name
                        or r.terminology_mapping.target_display
                    ),
                )
                obs_notes = None
            else:
                # Unmapped / ambiguous / review required: text only, NO empty coding array
                code_elem = CodeableConcept(
                    coding=None,
                    text=(
                        r.canonical_fields.test_name
                        or r.terminology_mapping.source_test_name
                        or "Laboratory Investigation"
                    ),
                )
                obs_notes = [
                    Annotation(
                        text=(
                            f"Clinical terminology unmapped (reason: {r.terminology_mapping.reason_code}). "
                            "Preserved with source investigation name."
                        )
                    )
                ]

            # Parse Numeric vs Text Value & UCUM Unit Attribution
            val_quantity: Optional[Quantity] = None
            val_string: Optional[str] = None
            raw_res = r.canonical_fields.result

            if isinstance(raw_res, (int, float)):
                unit_str = r.canonical_fields.unit.strip() if r.canonical_fields.unit else None
                if unit_str and unit_str in VERIFIED_UCUM_UNITS:
                    val_quantity = Quantity(
                        value=raw_res,
                        unit=unit_str,
                        system=UCUM_SYSTEM,
                        code=unit_str,
                    )
                elif unit_str:
                    val_quantity = Quantity(
                        value=raw_res,
                        unit=unit_str,
                    )
                else:
                    val_quantity = Quantity(value=raw_res)
            elif raw_res is not None:
                val_string = str(raw_res)

            # Link Specimen if available
            raw_spec = r.canonical_fields.specimen
            spec_ref: Optional[Reference] = None
            if raw_spec and raw_spec.strip():
                clean_spec = raw_spec.strip()
                if clean_spec in specimen_map:
                    spec_ref = Reference(reference=f"urn:uuid:{specimen_map[clean_spec][0]}")

            obs_res = Observation(
                id=obs_id,
                status="preliminary",
                category=[
                    CodeableConcept(
                        coding=[
                            Coding(
                                system=HL7_OBSERVATION_CATEGORY_SYSTEM,
                                code="laboratory",
                                display="Laboratory",
                            )
                        ]
                    )
                ],
                code=code_elem,
                subject=Reference(reference=f"urn:uuid:{pat_id}"),
                effectiveDateTime=r.canonical_fields.observed_at,
                valueQuantity=val_quantity,
                valueString=val_string,
                note=obs_notes,
                specimen=spec_ref,
            )
            observation_entries.append((obs_id, obs_res))

        # Build DiagnosticReport
        dr_status = "partial" if withheld_records_count > 0 else "preliminary"
        specimen_refs = (
            [Reference(reference=f"urn:uuid:{s_id}") for s_id, _ in specimen_map.values()]
            if specimen_map
            else None
        )
        result_refs = [Reference(reference=f"urn:uuid:{obs_id}") for obs_id, _ in observation_entries]

        dr_resource = DiagnosticReport(
            id=dr_id,
            status=dr_status,
            category=[
                CodeableConcept(
                    coding=[
                        Coding(
                            system=HL7_DIAGNOSTIC_SERVICE_SYSTEM,
                            code="LAB",
                            display="Laboratory",
                        )
                    ]
                )
            ],
            code=CodeableConcept(
                coding=[
                    Coding(
                        system=LOINC_SYSTEM,
                        code=LOINC_LAB_REPORT_CODE,
                        display=LOINC_LAB_REPORT_DISPLAY,
                    )
                ],
                text="Laboratory Diagnostic Report",
            ),
            subject=Reference(reference=f"urn:uuid:{pat_id}"),
            issued=current_timestamp,
            performer=[Reference(reference=f"urn:uuid:{org_id}")],
            specimen=specimen_refs,
            result=result_refs,
        )

        # Build Composition (omitting optional section.code and optional category)
        comp_resource = Composition(
            id=comp_id,
            status="preliminary",
            type=CodeableConcept(
                coding=[
                    Coding(
                        system=LOINC_SYSTEM,
                        code=LOINC_LAB_REPORT_CODE,
                        display=LOINC_LAB_REPORT_DISPLAY,
                    )
                ],
                text=LOINC_LAB_REPORT_DISPLAY,
            ),
            subject=Reference(reference=f"urn:uuid:{pat_id}", display="Patient"),
            date=current_timestamp,
            author=[Reference(reference=f"urn:uuid:{org_id}", display=request.batch.source_provider_id)],
            title="Laboratory Diagnostic Report",
            section=[
                CompositionSection(
                    title="Diagnostic Report",
                    entry=[Reference(reference=f"urn:uuid:{dr_id}")],
                )
            ],
        )

        # 6. Bundle Entries Construction (Composition first, strictly ordered)
        bundle_entries: List[BundleEntry] = [
            BundleEntry(fullUrl=f"urn:uuid:{comp_id}", resource=comp_resource),
            BundleEntry(fullUrl=f"urn:uuid:{pat_id}", resource=patient_resource),
            BundleEntry(fullUrl=f"urn:uuid:{org_id}", resource=organization_resource),
        ]

        # Specimen entries
        for spec_id, spec_res in specimen_map.values():
            bundle_entries.append(BundleEntry(fullUrl=f"urn:uuid:{spec_id}", resource=spec_res))

        # DiagnosticReport entry
        bundle_entries.append(BundleEntry(fullUrl=f"urn:uuid:{dr_id}", resource=dr_resource))

        # Observation entries
        for obs_id, obs_res in observation_entries:
            bundle_entries.append(BundleEntry(fullUrl=f"urn:uuid:{obs_id}", resource=obs_res))

        bundle = Bundle(
            id=bundle_id,
            identifier=Identifier(
                system="https://healthbridge.tn.gov.in/bundle",
                value=bundle_id,
            ),
            type="document",
            timestamp=current_timestamp,
            entry=bundle_entries,
        )

        envelope_status: str = "completed" if withheld_records_count == 0 else "partial"

        return FhirBundleAssemblyResponse(
            bundle_id=bundle_id,
            status=envelope_status,
            document_type="DiagnosticReportDocument",
            total_records=total_records,
            target_records_count=target_records_count,
            assembled_observations_count=assembled_observations_count,
            withheld_records_count=withheld_records_count,
            omitted_other_patient_count=omitted_other_patient_count,
            missing_patient_records_count=missing_patient_records_count,
            source_provider_id=request.batch.source_provider_id,
            patient_reference=target_pt,
            record_outcomes=record_outcomes,
            bundle=bundle,
        )
