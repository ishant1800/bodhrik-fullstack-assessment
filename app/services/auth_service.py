from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.auth import UserLogin, UserRegister


def get_user_by_email(db: Session, email: str) -> User | None:
    """Retrieve a user by their case-insensitive email address."""
    normalized_email = email.strip().lower()
    stmt = select(User).where(func.lower(User.email) == normalized_email)
    return db.execute(stmt).scalar_one_or_none()


def register_user(db: Session, user_in: UserRegister) -> User:
    """Register a new user account with customer role default and hashed password."""
    if get_user_by_email(db, user_in.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists",
        )

    hashed_pw = hash_password(user_in.password)
    user = User(
        name=user_in.name,
        email=user_in.email,
        password_hash=hashed_pw,
        role=UserRole.CUSTOMER,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists",
        )


def authenticate_user(db: Session, credentials: UserLogin) -> User:
    """Authenticate a user by verifying email and password hash.

    Raises:
        HTTPException: 401 Unauthorized on invalid email or password.
    """
    user = get_user_by_email(db, credentials.email)
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
