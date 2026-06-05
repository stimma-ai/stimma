"""
Middleware for multi-profile support.

Extracts profile ID from request headers and sets the profile context.
Validates PIN for protected profiles.
"""
from core.logging import get_logger
import hashlib
import traceback
from functools import lru_cache

import bcrypt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from core.profile_context import profile_context
from database_registry import get_database_registry
from config import get_settings

log = get_logger(__name__)

# Cache for PIN verification results: (profile_id, pin_hash, pin_sha256) -> True
# We hash the PIN with SHA256 as the cache key (fast) to avoid storing plaintext PINs
# The actual bcrypt verification only happens on cache miss
_pin_verification_cache: dict[tuple[str, str, str], bool] = {}


# Routes that don't require a profile (profile-agnostic endpoints)
# Note: These are checked with startswith(), except for exact matches like "/"
PROFILE_EXEMPT_EXACT = [
    "/",               # Root health check (exact match)
]
PROFILE_EXEMPT_PREFIXES = [
    "/api/profiles",   # Profile listing and management
    "/api/admin",      # Admin operations
    "/api/auth",       # Authentication (before profile selected)
    "/health",         # Health checks
    "/api/db/",        # db_guid routes handle their own profile resolution
    "/docs",           # API documentation
    "/openapi.json",   # OpenAPI schema
]

# Routes that don't require PIN verification (even if profile has PIN)
PIN_EXEMPT_PATHS = [
    "/api/profiles",   # Profile listing (includes has_pin flag)
]


def verify_pin(profile_id: str, pin: str, pin_hash: str) -> bool:
    """Verify a PIN against its bcrypt hash, with caching.

    Bcrypt is intentionally slow (~100ms), so we cache successful verifications.
    The cache key includes the pin_hash so it auto-invalidates when PIN changes.
    """
    # Create a fast hash of the PIN for cache lookup (don't store plaintext)
    pin_sha256 = hashlib.sha256(pin.encode('utf-8')).hexdigest()
    cache_key = (profile_id, pin_hash, pin_sha256)

    # Check cache first
    if cache_key in _pin_verification_cache:
        return True  # We only cache successful verifications

    # Cache miss - do the slow bcrypt check
    try:
        if bcrypt.checkpw(pin.encode('utf-8'), pin_hash.encode('utf-8')):
            _pin_verification_cache[cache_key] = True
            return True
        return False
    except Exception:
        return False


def clear_pin_cache(profile_id: str = None):
    """Clear the PIN verification cache.

    Call this when a profile's PIN is changed or removed.
    If profile_id is None, clears the entire cache.
    """
    global _pin_verification_cache
    if profile_id is None:
        _pin_verification_cache = {}
    else:
        _pin_verification_cache = {
            k: v for k, v in _pin_verification_cache.items()
            if k[0] != profile_id
        }


class ProfileMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts profile ID from request and sets context.

    The profile ID is read from the X-Profile-ID header or query param.
    Non-exempt routes return 400 if profile is missing or invalid.
    PIN-protected profiles require valid X-Profile-PIN header.
    """

    @staticmethod
    def _resolve_fallback_profile_id(registry) -> str | None:
        """Resolve a safe fallback profile ID for exempt routes."""
        profiles = registry.list_profiles()
        if profiles:
            return profiles[0]["id"]

        settings = get_settings()
        if settings.profiles:
            return settings.profiles[0].id

        return None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Check if this route is exempt from profile requirements
        is_exempt = (
            path in PROFILE_EXEMPT_EXACT or
            any(path.startswith(prefix) for prefix in PROFILE_EXEMPT_PREFIXES)
        )

        # Check if this route is exempt from PIN requirements
        is_pin_exempt = any(path.startswith(exempt) for exempt in PIN_EXEMPT_PATHS)

        # Get profile from header first, then query param (for img src URLs)
        profile_id = request.headers.get("X-Profile-ID")
        if not profile_id:
            profile_id = request.query_params.get("profile")

        registry = get_database_registry()

        # For non-exempt routes, validate profile is provided and exists
        if not is_exempt:
            if not profile_id:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "X-Profile-ID header or ?profile= query parameter required"}
                )
            if not registry.has_profile(profile_id):
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Invalid profile: {profile_id}"}
                )

            # Check PIN for protected profiles (unless PIN-exempt route)
            if not is_pin_exempt:
                settings = get_settings()
                profile_config = settings.get_profile(profile_id)
                if profile_config and profile_config.pin_hash:
                    # Profile requires PIN (header or query param for img src URLs)
                    pin = request.headers.get("X-Profile-PIN")
                    if not pin:
                        pin = request.query_params.get("pin")
                    if not pin:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": "PIN required",
                                "requires_pin": True,
                                "profile_id": profile_id
                            }
                        )
                    if not verify_pin(profile_id, pin, profile_config.pin_hash):
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": "Invalid PIN",
                                "requires_pin": True,
                                "profile_id": profile_id
                            }
                        )
        else:
            # For exempt routes, fall back to first available profile if missing/invalid
            if not profile_id or not registry.has_profile(profile_id):
                profile_id = self._resolve_fallback_profile_id(registry)

        # Set profile context for this request
        token = profile_context.set(profile_id)
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            # Log the full exception with traceback
            log.error(
                f"EXCEPTION in {request.method} {request.url.path}: {e}\n"
                f"{''.join(traceback.format_exception(type(e), e, e.__traceback__))}"
            )
            raise
        finally:
            profile_context.reset(token)
