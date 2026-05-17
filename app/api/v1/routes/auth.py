"""
Authentication routes.

POST /api/v1/auth/token  →  issue a JWT
GET  /api/v1/auth/me     →  return current user info
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.security import (
    TokenResponse,
    authenticate_user,
    create_access_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Issue a JWT for a valid username/password pair.

    Demo credentials: demo / demo1234
    """
    username = authenticate_user(form_data.username, form_data.password)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=username)
    return TokenResponse(access_token=token)


@router.get("/me")
async def me(current_user: str = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return {"username": current_user}
