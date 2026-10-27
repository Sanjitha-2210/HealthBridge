"""Custom exceptions and error response representations for M1 Ingestion."""
from typing import Optional


class IngestionException(Exception):
    """Base exception for all ingestion layer errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "INGESTION_ERROR",
        status_code: int = 400,
        details: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details


class InvalidProviderError(IngestionException):
    """Raised when an unauthenticated, unknown, or conflicting provider ID is supplied."""

    def __init__(self, provider_id: Optional[str] = None, message: Optional[str] = None):
        if message is None:
            message = (
                f"Provider ID '{provider_id}' is not authorized. Must be one of the configured providers."
                if provider_id
                else "Provider ID is required. Supply via 'X-Provider-ID' header or 'source_provider_id' field."
            )
        super().__init__(
            message=message,
            error_code="INVALID_PROVIDER_ID",
            status_code=400,
        )


class PayloadTooLargeError(IngestionException):
    """Raised when the upload size exceeds configured limits."""

    def __init__(self, max_bytes: int):
        super().__init__(
            message=f"Payload size exceeds maximum allowed limit of {max_bytes} bytes.",
            error_code="PAYLOAD_TOO_LARGE",
            status_code=413,
        )


class UnsupportedMediaTypeError(IngestionException):
    """Raised when an unsupported file type or content-type is uploaded."""

    def __init__(self, message: str = "Unsupported media type or file format."):
        super().__init__(
            message=message,
            error_code="UNSUPPORTED_MEDIA_TYPE",
            status_code=415,
        )


class MalformedPayloadError(IngestionException):
    """Raised when CSV or JSON structure is corrupted, unparseable, or inconsistent."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="MALFORMED_PAYLOAD",
            status_code=400,
        )


class EmptyPayloadError(IngestionException):
    """Raised when an upload contains no content or no clinical records."""

    def __init__(self, message: str = "Payload contains no data records."):
        super().__init__(
            message=message,
            error_code="EMPTY_PAYLOAD",
            status_code=400,
        )


class RecordLimitExceededError(IngestionException):
    """Raised when the number of records exceeds the configured maximum limit."""

    def __init__(self, record_count: int, max_records: int):
        super().__init__(
            message=f"Record count ({record_count}) exceeds maximum allowed limit of {max_records} records.",
            error_code="RECORD_LIMIT_EXCEEDED",
            status_code=400,
        )


class NormalizationException(Exception):
    """Base exception for all normalization layer errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "NORMALIZATION_ERROR",
        status_code: int = 400,
        details: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details


class NormalizationConfigurationError(NormalizationException):
    """Raised when no mapping configuration exists or configuration is invalid."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="NORMALIZATION_CONFIG_ERROR",
            status_code=400,
        )


class InvalidEnvelopeError(NormalizationException):
    """Raised when an incoming M1 ingestion envelope is malformed or invalid."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="INVALID_ENVELOPE",
            status_code=400,
        )


class NormalizationRecordLimitExceededError(NormalizationException):
    """Raised when the number of records in an M2 normalization batch exceeds the configured limit."""

    def __init__(self, record_count: int, max_records: int):
        super().__init__(
            message=f"Batch record count ({record_count}) exceeds maximum allowed limit of {max_records} records.",
            error_code="RECORD_LIMIT_EXCEEDED",
            status_code=400,
        )


class TerminologyException(Exception):
    """Base exception for all terminology mapping layer errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "TERMINOLOGY_ERROR",
        status_code: int = 400,
        details: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details


class TerminologyConfigurationError(TerminologyException):
    """Raised when terminology registry configuration is invalid, corrupted, or contains duplicate IDs."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="TERMINOLOGY_CONFIG_ERROR",
            status_code=400,
        )


class InvalidTerminologyRequestError(TerminologyException):
    """Raised when an incoming terminology mapping request or envelope is malformed or invalid."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="INVALID_TERMINOLOGY_REQUEST",
            status_code=400,
        )


class EmptyTerminologyBatchError(TerminologyException):
    """Raised when an incoming terminology request contains no records."""

    def __init__(self, message: str = "Terminology batch contains no records."):
        super().__init__(
            message=message,
            error_code="EMPTY_PAYLOAD",
            status_code=400,
        )


class TerminologyRecordLimitExceededError(TerminologyException):
    """Raised when the number of records in a terminology batch exceeds configured limits."""

    def __init__(self, record_count: int, max_records: int):
        super().__init__(
            message=f"Batch record count ({record_count}) exceeds maximum allowed limit of {max_records} records.",
            error_code="RECORD_LIMIT_EXCEEDED",
            status_code=400,
        )


class IdentityException(Exception):
    """Base exception for all patient identity safety layer errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "IDENTITY_ERROR",
        status_code: int = 400,
        details: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details


class IdentityConfigurationError(IdentityException, ValueError):
    """Raised when identity configuration or rules are invalid."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="IDENTITY_CONFIG_ERROR",
            status_code=400,
        )


class InvalidIdentityRequestError(IdentityException):
    """Raised when an incoming identity assessment request is malformed or invalid."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="INVALID_IDENTITY_REQUEST",
            status_code=400,
        )


class EmptyIdentityBatchError(IdentityException):
    """Raised when an incoming identity assessment batch contains no comparisons."""

    def __init__(self, message: str = "Identity assessment batch contains no comparisons."):
        super().__init__(
            message=message,
            error_code="EMPTY_PAYLOAD",
            status_code=400,
        )


class IdentityRecordLimitExceededError(IdentityException):
    """Raised when the number of comparisons in an identity batch exceeds configured limits."""

    def __init__(self, comparison_count: int, max_comparisons: int):
        super().__init__(
            message=f"Batch comparison count ({comparison_count}) exceeds maximum allowed limit of {max_comparisons} comparisons.",
            error_code="RECORD_LIMIT_EXCEEDED",
            status_code=400,
        )


class FhirException(Exception):
    """Base exception for all M5 FHIR R4 Bundle Assembly layer errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "FHIR_ASSEMBLY_ERROR",
        status_code: int = 400,
        details: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details


class InvalidFhirRequestError(FhirException):
    """Raised when an incoming FHIR bundle assembly request is malformed or invalid."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="INVALID_FHIR_REQUEST",
            status_code=400,
        )


class EmptyFhirBatchError(FhirException):
    """Raised when an incoming FHIR bundle assembly batch contains no records."""

    def __init__(self, message: str = "FHIR bundle assembly batch contains no records."):
        super().__init__(
            message=message,
            error_code="EMPTY_PAYLOAD",
            status_code=400,
        )


class FhirRecordLimitExceededError(FhirException):
    """Raised when the number of records in a FHIR assembly batch exceeds configured limits."""

    def __init__(self, record_count: int, max_records: int):
        super().__init__(
            message=f"Batch record count ({record_count}) exceeds maximum allowed limit of {max_records} records.",
            error_code="RECORD_LIMIT_EXCEEDED",
            status_code=400,
        )


class MixedPatientBatchError(FhirException):
    """Raised when a batch contains multiple patients or missing patient references without a filter."""

    def __init__(self, message: str = "Batch contains multiple patient references; explicit patient_reference filter is required."):
        super().__init__(
            message=message,
            error_code="MIXED_PATIENT_BATCH",
            status_code=400,
        )


class FhirAssemblyError(FhirException):
    """Raised when technical FHIR bundle assembly cannot produce any valid observations (e.g. all rejected)."""

    def __init__(self, message: str = "FHIR bundle assembly failed; no valid observations could be assembled."):
        super().__init__(
            message=message,
            error_code="FHIR_ASSEMBLY_FAILED",
            status_code=422,
        )


class GatewayException(Exception):
    """Base exception for all M6 ABDM Security Gateway errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "GATEWAY_SECURITY_ERROR",
        status_code: int = 403,
        details: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details


class ConsentExpiredError(GatewayException):
    """Raised when a consent artefact status is EXPIRED or temporal validity has lapsed."""

    def __init__(self, message: str = "Consent artefact has expired."):
        super().__init__(
            message=message,
            error_code="CONSENT_EXPIRED",
            status_code=403,
        )


class ConsentRevokedError(GatewayException):
    """Raised when a consent artefact status is REVOKED."""

    def __init__(self, message: str = "Consent artefact has been revoked by the patient."):
        super().__init__(
            message=message,
            error_code="CONSENT_REVOKED",
            status_code=403,
        )


class ConsentDeniedError(GatewayException):
    """Raised when a consent request was explicitly DENIED."""

    def __init__(self, message: str = "Consent request was denied by the patient."):
        super().__init__(
            message=message,
            error_code="CONSENT_DENIED",
            status_code=403,
        )


class ConsentNotGrantedError(GatewayException):
    """Raised when consent is in REQUESTED or any non-GRANTED state."""

    def __init__(self, message: str = "Consent has not been granted."):
        super().__init__(
            message=message,
            error_code="CONSENT_NOT_GRANTED",
            status_code=403,
        )


class ConsentRetentionExpiredError(GatewayException):
    """Raised when current time has reached or exceeded data_erase_at retention boundary."""

    def __init__(self, message: str = "Data retention period has expired under data_erase_at boundary."):
        super().__init__(
            message=message,
            error_code="CONSENT_RETENTION_EXPIRED",
            status_code=403,
        )


class ConsentPatientMismatchError(GatewayException):
    """Raised when consent patient identity does not match bundle patient identity."""

    def __init__(self, message: str = "Patient identity in consent artefact does not match bundle patient."):
        super().__init__(
            message=message,
            error_code="CONSENT_PATIENT_MISMATCH",
            status_code=403,
        )


class ConsentHipMismatchError(GatewayException):
    """Raised when consent HIP identity does not match the source provider."""

    def __init__(self, message: str = "Health Information Provider (HIP) does not match source organization."):
        super().__init__(
            message=message,
            error_code="CONSENT_HIP_MISMATCH",
            status_code=403,
        )


class ConsentHiuMismatchError(GatewayException):
    """Raised when the requesting HIU is not authorized by the consent artefact."""

    def __init__(self, message: str = "Requesting Health Information User (HIU) is not authorized by consent."):
        super().__init__(
            message=message,
            error_code="CONSENT_HIU_MISMATCH",
            status_code=403,
        )


class ConsentHiTypeMismatchError(GatewayException):
    """Raised when consent artefact does not authorize the requested health information type."""

    def __init__(self, message: str = "Consent does not authorize the required Health Information Type."):
        super().__init__(
            message=message,
            error_code="CONSENT_HI_TYPE_MISMATCH",
            status_code=403,
        )


class ConsentDateOutOfRangeError(GatewayException):
    """Raised when one or more observations fall outside the consented clinical date range."""

    def __init__(self, message: str = "One or more observations fall outside the consented date range."):
        super().__init__(
            message=message,
            error_code="CONSENT_DATE_OUT_OF_RANGE",
            status_code=403,
        )


class InvalidClinicalTimestampError(GatewayException):
    """Raised when an observation has a missing or unparseable clinical timestamp under fail-closed policy."""

    def __init__(self, message: str = "Observation clinical timestamp is missing or invalid; fail-closed."):
        super().__init__(
            message=message,
            error_code="INVALID_CLINICAL_TIMESTAMP",
            status_code=403,
        )


class InvalidConsentSignatureError(GatewayException):
    """Raised when consent digital signature is invalid, missing, or unsupported."""

    def __init__(self, message: str = "Consent digital signature verification failed."):
        super().__init__(
            message=message,
            error_code="INVALID_CONSENT_SIGNATURE",
            status_code=403,
        )


class InvalidGatewayRequestError(GatewayException):
    """Raised when release request structure or bundle payload is structurally malformed."""

    def __init__(self, message: str = "Invalid gateway release request payload."):
        super().__init__(
            message=message,
            error_code="INVALID_GATEWAY_REQUEST",
            status_code=400,
        )



