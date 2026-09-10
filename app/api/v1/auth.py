from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse, UserLogin, UserRegister
from app.schemas.user import UserResponse
from app.services import auth_service

router = APIRouter()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
def register(
    user_in: UserRegister,
    db: Session = Depends(get_db),
) -> User:
    """Register a new user account with default customer role.

    - **name**: User's full name
    - **email**: Unique email address (normalized to lowercase)
    - **password**: Plaintext password (at least 8 characters, hashed securely)
    """
    return auth_service.register_user(db=db, user_in=user_in)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain JWT access token",
)
def login(
    credentials: UserLogin,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate user with email and password and return signed JWT Bearer token."""
    user = auth_service.authenticate_user(db=db, credentials=credentials)
    access_token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=access_token, token_type="bearer")


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current authenticated user profile",
)
def get_me(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return the profile information of the currently authenticated user."""
    return current_user
