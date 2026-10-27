"""Application configuration using Pydantic Settings."""
from functools import lru_cache
from typing import Set, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for TN HealthBridge M1 Data Ingestion Layer."""
    
    # Environment & API metadata
    ENVIRONMENT: str = "development"
    PROJECT_NAME: str = "TN HealthBridge"
    API_V1_PREFIX: str = "/api/v1"
    
    # Ingestion, normalization & terminology constraints
    MAX_UPLOAD_SIZE_BYTES: int = 1_048_576  # 1 MB
    MAX_RECORD_COUNT: int = 1_000
    MAX_NORMALIZATION_RECORD_COUNT: int = 1_000
    MAX_TERMINOLOGY_RECORD_COUNT: int = 1_000
    MAX_IDENTITY_RECORD_COUNT: int = 1_000
    
    # Simulated provider allowlist
    ALLOWED_PROVIDERS: Union[Set[str], str] = {
        "HOSPITAL_A",
        "HOSPITAL_B",
        "LAB_C",
    }

    # Authoritative synthetic identity fixture registry path
    SYNTHETIC_IDENTITY_REGISTRY_PATH: str = "data/identity/synthetic_identity_registry.json"

    # M6 Security Gateway configuration (strictly disabled by default; forbidden in production)
    ALLOW_TEST_SIGNATURES: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    @field_validator("ALLOWED_PROVIDERS", mode="before")
    @classmethod
    def parse_allowed_providers(cls, v: Union[Set[str], list, str]) -> Set[str]:
        if isinstance(v, str):
            return {p.strip() for p in v.split(",") if p.strip()}
        if isinstance(v, (list, set)):
            return {str(p).strip() for p in v if str(p).strip()}
        return set()



@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
