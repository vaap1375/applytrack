from functools import lru_cache
from uuid import UUID
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import settings

bearer = HTTPBearer(auto_error=False)

@lru_cache
def jwks_client(url: str):
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=300, timeout=5)

def current_owner(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> UUID:
    config = settings()
    if not config.supabase_url or not config.owner_id:
        raise HTTPException(503, "Authentication is not configured")
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    issuer = config.supabase_url.rstrip("/") + "/auth/v1"
    try:
        key = jwks_client(issuer + "/.well-known/jwks.json").get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(credentials.credentials, key.key, algorithms=["ES256", "RS256"], audience="authenticated", issuer=issuer, options={"require": ["exp", "sub", "aud", "iss"]})
        owner = UUID(claims["sub"])
        allowed = UUID(config.owner_id)
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "Invalid or expired access token") from None
    if owner != allowed:
        raise HTTPException(403, "This account is not authorized")
    return owner
