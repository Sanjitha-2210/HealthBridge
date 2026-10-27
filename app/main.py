"""Main entry point for TN HealthBridge FastAPI application."""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import (
    fhir_router,
    gateway_router,
    identity_router,
    ingestion_router,
    normalization_router,
    terminology_router,
)
from app.core.config import get_settings
from app.core.errors import (
    FhirException,
    GatewayException,
    IdentityException,
    IngestionException,
    NormalizationException,
    TerminologyException,
)

from app.core.identity_config import load_synthetic_identity_registry

# Configure centralized safe logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tn_healthbridge")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for application startup and shutdown events."""
    settings = get_settings()
    logger.info("Starting %s in %s mode", settings.PROJECT_NAME, settings.ENVIRONMENT)
    
    # Validate synthetic identity registry configuration at startup against configured allowlist
    load_synthetic_identity_registry(
        settings.SYNTHETIC_IDENTITY_REGISTRY_PATH,
        allowed_providers=settings.ALLOWED_PROVIDERS,
    )

    logger.info(
        "M1 Ingestion, M2 Normalization, M3 Terminology Mapping & M4 Patient Identity Safety active. "
        "Central clinical storage: DISABLED."
    )
    yield
    logger.info("Shutting down %s", settings.PROJECT_NAME)




def create_application() -> FastAPI:
    """Factory creating and configuring the FastAPI instance."""
    settings = get_settings()

    app = FastAPI(
        title="TN HealthBridge — Interoperability Middleware",
        description=(
            "Healthcare interoperability middleware prototype. "
            "M1 Ingestion, M2 Normalization, M3 Terminology Mapping, and M4 Patient Identity Safety "
            "provide uncertainty-aware clinical data exchange without creating a central patient database."
        ),
        version="0.2.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. Custom exception handler for domain ingestion exceptions
    @app.exception_handler(IngestionException)
    async def ingestion_exception_handler(request: Request, exc: IngestionException) -> JSONResponse:
        logger.warning(
            "Ingestion error: code=%s, status=%d, message=%s",
            exc.error_code,
            exc.status_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
            },
        )

    # 2. Custom exception handler for domain normalization exceptions
    @app.exception_handler(NormalizationException)
    async def normalization_exception_handler(request: Request, exc: NormalizationException) -> JSONResponse:
        logger.warning(
            "Normalization error: code=%s, status=%d, message=%s",
            exc.error_code,
            exc.status_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
            },
        )

    # 3. Custom exception handler for domain terminology exceptions
    @app.exception_handler(TerminologyException)
    async def terminology_exception_handler(request: Request, exc: TerminologyException) -> JSONResponse:
        logger.warning(
            "Terminology error: code=%s, status=%d, message=%s",
            exc.error_code,
            exc.status_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
            },
        )

    # 4. Custom exception handler for domain patient identity exceptions
    @app.exception_handler(IdentityException)
    async def identity_exception_handler(request: Request, exc: IdentityException) -> JSONResponse:
        logger.warning(
            "Identity safety error: code=%s, status=%d, message=%s",
            exc.error_code,
            exc.status_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
            },
        )

    # 5. Custom exception handler for domain FHIR bundle assembly exceptions
    @app.exception_handler(FhirException)
    async def fhir_exception_handler(request: Request, exc: FhirException) -> JSONResponse:
        logger.warning(
            "FHIR assembly error: code=%s, status=%d, message=%s",
            exc.error_code,
            exc.status_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
            },
        )

    # 6. Custom exception handler for domain ABDM security gateway exceptions
    @app.exception_handler(GatewayException)
    async def gateway_exception_handler(request: Request, exc: GatewayException) -> JSONResponse:
        logger.warning(
            "Gateway security error: code=%s, status=%d, message=%s",
            exc.error_code,
            exc.status_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
            },
        )

    # 7. Custom handler for request validation errors (Pydantic / FastAPI 422)
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Provide a safe error message without leaking sensitive payload data
        logger.warning("Validation error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error_code": "VALIDATION_ERROR",
                "message": "The request content failed validation. Check parameters and payload structure.",
            },
        )

    # 8. Global fallback exception handler ensuring no raw stack traces leak
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled server exception: %s", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred while processing the request.",
            },
        )

    # 9. Health Check Endpoint
    @app.get(
        "/health",
        tags=["System"],
        summary="Service Health Check",
        description="Verify service availability without exposing sensitive internal state.",
    )
    async def health_check() -> dict:
        return {
            "status": "healthy",
            "service": "TN HealthBridge",
            "module": "M1_DATA_INGESTION",
            "modules": [
                "M1_DATA_INGESTION",
                "M2_DATA_NORMALIZATION",
                "M3_CLINICAL_TERMINOLOGY_MAPPING",
                "M4_PATIENT_IDENTITY_SAFETY",
                "M5_FHIR_BUNDLE_ASSEMBLY",
                "M6_CONSENT_SECURITY_GATEWAY",
            ],
        }

    # 10. Register API Routers
    app.include_router(ingestion_router, prefix=settings.API_V1_PREFIX)
    app.include_router(normalization_router, prefix=settings.API_V1_PREFIX)
    app.include_router(terminology_router, prefix=settings.API_V1_PREFIX)
    app.include_router(identity_router, prefix=settings.API_V1_PREFIX)
    app.include_router(fhir_router, prefix=settings.API_V1_PREFIX)
    app.include_router(gateway_router, prefix=settings.API_V1_PREFIX)


    return app


app = create_application()
