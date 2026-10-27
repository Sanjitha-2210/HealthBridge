"""Pydantic schemas for M5 FHIR R4 Bundle Assembly Layer."""
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.terminology import TerminologyBatchResponse


class Coding(BaseModel):
    """FHIR R4 Coding data type."""
    model_config = ConfigDict(extra="ignore")

    system: Optional[str] = Field(default=None, description="Identity of the terminology system.")
    code: Optional[str] = Field(default=None, description="Symbol in syntax defined by the system.")
    display: Optional[str] = Field(default=None, description="Representation defined by the system.")


class CodeableConcept(BaseModel):
    """FHIR R4 CodeableConcept data type."""
    model_config = ConfigDict(extra="ignore")

    coding: Optional[List[Coding]] = Field(
        default=None,
        description="Code defined by a terminology system.",
    )
    text: Optional[str] = Field(
        default=None,
        description="Plain text representation of the concept.",
    )


class Reference(BaseModel):
    """FHIR R4 Reference data type."""
    model_config = ConfigDict(extra="ignore")

    reference: str = Field(..., description="Literal reference, relative, internal or absolute URL.")
    display: Optional[str] = Field(default=None, description="Text alternative for the resource.")


class Identifier(BaseModel):
    """FHIR R4 Identifier data type."""
    model_config = ConfigDict(extra="ignore")

    system: Optional[str] = Field(default=None, description="The namespace for the identifier value.")
    value: Optional[str] = Field(default=None, description="The value that is unique within the system.")


class Quantity(BaseModel):
    """FHIR R4 Quantity data type."""
    model_config = ConfigDict(extra="ignore")

    value: Optional[Union[int, float]] = Field(default=None, description="Numerical value.")
    unit: Optional[str] = Field(default=None, description="Unit representation from source.")
    system: Optional[str] = Field(default=None, description="Identity of the unit system (e.g. UCUM).")
    code: Optional[str] = Field(default=None, description="Coded form of the unit.")


class Annotation(BaseModel):
    """FHIR R4 Annotation data type."""
    model_config = ConfigDict(extra="ignore")

    text: str = Field(..., description="The annotation content text.")


class ResourceMeta(BaseModel):
    """FHIR R4 Resource Metadata."""
    model_config = ConfigDict(extra="ignore")

    versionId: Optional[str] = Field(default=None, description="Version specific identifier.")
    lastUpdated: Optional[str] = Field(default=None, description="When the resource version last changed.")
    profile: Optional[List[str]] = Field(default=None, description="Profiles this resource claims to conform to.")


class CompositionSection(BaseModel):
    """FHIR R4 Composition Section."""
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = Field(default=None, description="Label for section.")
    code: Optional[CodeableConcept] = Field(default=None, description="Classification of section.")
    entry: List[Reference] = Field(default_factory=list, description="References to resources in this section.")


class Composition(BaseModel):
    """FHIR R4 Composition resource."""
    model_config = ConfigDict(extra="ignore")

    resourceType: Literal["Composition"] = "Composition"
    id: str = Field(..., description="Logical id of this artifact.")
    meta: Optional[ResourceMeta] = None
    status: Literal["preliminary", "final", "amended", "entered-in-error"] = Field(
        default="preliminary",
        description="preliminary | final | amended | entered-in-error",
    )
    type: CodeableConcept = Field(..., description="Kind of composition (LOINC 11502-2 for lab report).")
    category: Optional[List[CodeableConcept]] = None
    subject: Reference = Field(..., description="Who and/or what the composition is about.")
    date: str = Field(..., description="Composition editing time.")
    author: List[Reference] = Field(..., description="Who and/or what authored the composition.")
    title: str = Field(default="Laboratory Diagnostic Report", description="Human Readable name/title.")
    section: List[CompositionSection] = Field(default_factory=list, description="Composition is broken into sections.")
    attester: Optional[List[Any]] = None


class Patient(BaseModel):
    """FHIR R4 Patient resource."""
    model_config = ConfigDict(extra="ignore")

    resourceType: Literal["Patient"] = "Patient"
    id: str = Field(..., description="Logical id of this artifact.")
    meta: Optional[ResourceMeta] = None
    identifier: List[Identifier] = Field(default_factory=list, description="An identifier for this patient.")
    active: Optional[bool] = Field(default=True, description="Whether this patient's record is in active use.")


class Organization(BaseModel):
    """FHIR R4 Organization resource."""
    model_config = ConfigDict(extra="ignore")

    resourceType: Literal["Organization"] = "Organization"
    id: str = Field(..., description="Logical id of this artifact.")
    meta: Optional[ResourceMeta] = None
    identifier: List[Identifier] = Field(default_factory=list, description="Identifies this organization across systems.")
    name: Optional[str] = Field(default=None, description="Name used for the organization.")


class SpecimenType(BaseModel):
    """Specimen kind or type description."""
    model_config = ConfigDict(extra="ignore")

    text: Optional[str] = None
    coding: Optional[List[Coding]] = None


class Specimen(BaseModel):
    """FHIR R4 Specimen resource."""
    model_config = ConfigDict(extra="ignore")

    resourceType: Literal["Specimen"] = "Specimen"
    id: str = Field(..., description="Logical id of this artifact.")
    meta: Optional[ResourceMeta] = None
    type: Optional[SpecimenType] = Field(default=None, description="Kind of material that forms the specimen.")
    subject: Optional[Reference] = Field(default=None, description="Where the specimen came from.")
    collection: Optional[Dict[str, Any]] = None


class DiagnosticReport(BaseModel):
    """FHIR R4 DiagnosticReport resource."""
    model_config = ConfigDict(extra="ignore")

    resourceType: Literal["DiagnosticReport"] = "DiagnosticReport"
    id: str = Field(..., description="Logical id of this artifact.")
    meta: Optional[ResourceMeta] = None
    status: Literal[
        "registered",
        "partial",
        "preliminary",
        "final",
        "amended",
        "corrected",
        "appended",
        "cancelled",
        "entered-in-error",
        "unknown",
    ] = Field(default="preliminary", description="Status of the diagnostic report.")
    category: Optional[List[CodeableConcept]] = None
    code: CodeableConcept = Field(..., description="Name/Code for this diagnostic report.")
    subject: Reference = Field(..., description="The subject of the report.")
    issued: Optional[str] = Field(default=None, description="DateTime this version was made.")
    performer: Optional[List[Reference]] = None
    specimen: Optional[List[Reference]] = None
    result: List[Reference] = Field(default_factory=list, description="Observations that are part of this report.")


class Observation(BaseModel):
    """FHIR R4 Observation resource."""
    model_config = ConfigDict(extra="ignore")

    resourceType: Literal["Observation"] = "Observation"
    id: str = Field(..., description="Logical id of this artifact.")
    meta: Optional[ResourceMeta] = None
    status: Literal[
        "registered",
        "preliminary",
        "final",
        "amended",
        "corrected",
        "cancelled",
        "entered-in-error",
        "unknown",
    ] = Field(default="preliminary", description="Observation status.")
    category: Optional[List[CodeableConcept]] = None
    code: CodeableConcept = Field(..., description="Type of observation (code / type).")
    subject: Reference = Field(..., description="Who and/or what the observation is about.")
    effectiveDateTime: Optional[str] = Field(default=None, description="Clinically relevant time/time-period.")
    valueQuantity: Optional[Quantity] = None
    valueString: Optional[str] = None
    note: Optional[List[Annotation]] = None
    specimen: Optional[Reference] = None


class BundleEntry(BaseModel):
    """FHIR R4 Bundle Entry."""
    model_config = ConfigDict(extra="ignore")

    fullUrl: str = Field(..., description="URI for resource.")
    resource: Union[Composition, Patient, Organization, Specimen, DiagnosticReport, Observation, Dict[str, Any]] = Field(
        ...,
        description="A resource in the bundle.",
    )


class Bundle(BaseModel):
    """FHIR R4 Document Bundle resource."""
    model_config = ConfigDict(extra="ignore")

    resourceType: Literal["Bundle"] = "Bundle"
    id: str = Field(..., description="Logical id of this artifact.")
    meta: Optional[ResourceMeta] = None
    identifier: Optional[Identifier] = None
    type: Literal["document"] = "document"
    timestamp: str = Field(..., description="When the bundle was assembled.")
    entry: List[BundleEntry] = Field(default_factory=list, description="Entry in the bundle.")


RecordOutcomeType = Literal[
    "assembled_loinc_mapped",
    "assembled_text_only_unmapped",
    "withheld_quality_rejection",
    "withheld_missing_patient_reference",
    "omitted_other_patient",
]


class RecordAssemblyOutcome(BaseModel):
    """Outcome of technical assembly evaluation for a single batch record."""
    model_config = ConfigDict(extra="ignore")

    record_index: int = Field(..., description="Index of the record in the original input batch.")
    outcome: RecordOutcomeType = Field(..., description="Categorization of assembly outcome.")
    reason_code: str = Field(..., description="Machine-readable reason classification code.")
    message: str = Field(..., description="Human-readable explanation of outcome.")


class FhirBundleAssemblyRequest(BaseModel):
    """Request payload for M5 FHIR R4 Bundle Assembly."""
    model_config = ConfigDict(extra="ignore")

    batch: TerminologyBatchResponse = Field(
        ...,
        description="Terminology mapped batch response from M3.",
    )
    patient_reference: Optional[str] = Field(
        default=None,
        description="Target patient reference to assemble. Required for mixed-patient batches.",
    )


class FhirBundleAssemblyResponse(BaseModel):
    """Response envelope for M5 FHIR R4 Bundle Assembly."""
    model_config = ConfigDict(extra="ignore")

    bundle_id: str = Field(..., description="Unique UUID for this assembled FHIR bundle.")
    status: Literal["completed", "partial"] = Field(
        ...,
        description="Assembly status for the target patient document.",
    )
    document_type: str = Field(
        default="DiagnosticReportDocument",
        description="Document type classification.",
    )
    total_records: int = Field(..., description="Total records in the input batch.")
    target_records_count: int = Field(..., description="Total records matching the target patient.")
    assembled_observations_count: int = Field(..., description="Number of Observation resources assembled.")
    withheld_records_count: int = Field(..., description="Target patient records withheld due to quality rejection.")
    omitted_other_patient_count: int = Field(..., description="Records belonging to other patients excluded.")
    missing_patient_records_count: int = Field(..., description="Records lacking a patient reference excluded.")
    source_provider_id: str = Field(..., description="Source healthcare provider identifier.")
    patient_reference: str = Field(..., description="Subject patient reference for this document.")
    record_outcomes: List[RecordAssemblyOutcome] = Field(
        default_factory=list,
        description="Per-record assembly outcomes across all input batch records.",
    )
    bundle: Bundle = Field(..., description="Assembled FHIR R4 document bundle.")
