import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi import APIRouter, Depends, status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.session import SessionLocal
from app.main import app
from app.models.enums import UserRole
from app.models.user import User

# ---------------------------------------------------------------------------
# Test-Only Router for RBAC Testing (NEVER added to production app)
# ---------------------------------------------------------------------------
rbac_test_router = APIRouter(prefix="/test-rbac-only", tags=["test-rbac"])


@rbac_test_router.get("/admin-only")
def admin_only_endpoint(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict[str, Any]:
    """Test endpoint restricted to admins only."""
    return {"message": "admin_granted", "user_id": str(current_user.id)}


@rbac_test_router.get("/staff-only")
def staff_only_endpoint(
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.PROVIDER)),
) -> dict[str, Any]:
    """Test endpoint restricted to admin or provider."""
    return {
        "message": "staff_granted",
        "role": current_user.role.value,
        "user_id": str(current_user.id),
    }


# Include test-only router in the app during test execution
app.include_router(rbac_test_router)


# ---------------------------------------------------------------------------
# Database Session & Cleanup Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def db() -> Session:
    """Yield a database session for test verification and fixture setup."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def cleanup_test_users():
    """Clean up any users created with test emails after each test."""
    yield
    session = SessionLocal()
    try:
        users = (
            session.execute(
                select(User).where(User.email.like("%@testauth.example.com"))
            )
            .scalars()
            .all()
        )
        for u in users:
            session.delete(u)
        session.commit()
    finally:
        session.close()


def create_test_user(
    db: Session,
    email: str,
    password: str = "securePassword123",
    role: UserRole = UserRole.CUSTOMER,
    name: str = "Test User",
) -> User:
    """Helper to create a user directly in the database."""
    user = User(
        name=name,
        email=email.strip().lower(),
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ===========================================================================
# 1. Cryptographic and JWT Security Unit Tests
# ===========================================================================
def test_hash_password_generates_valid_bcrypt_hash() -> None:
    """Verify hash_password generates distinct bcrypt hashes with unique salts."""
    pwd = "mySuperSecretPassword"
    hash1 = hash_password(pwd)
    hash2 = hash_password(pwd)

    assert hash1.startswith("$2b$")
    assert hash2.startswith("$2b$")
    assert hash1 != hash2, "Bcrypt salt must be unique per invocation"
    assert verify_password(pwd, hash1) is True
    assert verify_password(pwd, hash2) is True


def test_verify_password_correct_and_incorrect() -> None:
    """Verify verify_password correctly validates matches and rejections."""
    pwd = "correctPassword123"
    wrong_pwd = "wrongPassword456"
    hashed = hash_password(pwd)

    assert verify_password(pwd, hashed) is True
    assert verify_password(wrong_pwd, hashed) is False
    assert verify_password(pwd, "invalid_hash_string") is False


def test_create_and_decode_access_token() -> None:
    """Verify access token generation and decoding preserve claims."""
    subject = str(uuid.uuid4())
    token = create_access_token(subject=subject)

    payload = decode_access_token(token)
    assert payload["sub"] == subject
    assert "iat" in payload
    assert "exp" in payload
    assert payload["exp"] > payload["iat"]


def test_decode_access_token_expired() -> None:
    """Verify expired token raises jwt.PyJWTError on decode."""
    subject = str(uuid.uuid4())
    # Create an already expired token
    expired_token = create_access_token(
        subject=subject,
        expires_delta=timedelta(seconds=-10),
    )
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(expired_token)


def test_decode_access_token_tampered() -> None:
    """Verify tampered token raises jwt.PyJWTError on decode."""
    token = create_access_token(subject=str(uuid.uuid4()))
    tampered_token = token[:-4] + "abcd"
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered_token)


def test_decode_access_token_invalid_secret() -> None:
    """Verify token signed with an invalid secret fails decoding."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    fake_token = jwt.encode(
        payload,
        "wrong_secret_key_at_least_32_bytes_long!!",
        algorithm="HS256",
    )
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(fake_token)


# ===========================================================================
# 2. Registration Endpoint Integration Tests
# ===========================================================================
def test_register_user_success(client: TestClient, db: Session) -> None:
    """Verify successful user registration returns 201 Created and customer role."""
    unique_email = f"register_{uuid.uuid4().hex[:8]}@testauth.example.com"
    payload = {
        "name": "Jane Doe",
        "email": unique_email,
        "password": "Password123!",
    }

    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert "id" in data
    assert data["name"] == "Jane Doe"
    assert data["email"] == unique_email.lower()
    assert data["role"] == "customer"
    assert "created_at" in data
    assert "updated_at" in data
    assert "password" not in data
    assert "password_hash" not in data


def test_register_user_password_is_hashed_in_db(
    client: TestClient, db: Session
) -> None:
    """Verify database securely stores bcrypt hash and not plaintext password."""
    unique_email = f"hashcheck_{uuid.uuid4().hex[:8]}@testauth.example.com"
    plain_password = "SuperSecretPassword123"
    payload = {
        "name": "Secure User",
        "email": unique_email,
        "password": plain_password,
    }

    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    user_id = uuid.UUID(response.json()["id"])

    # Query DB directly to verify password hash
    db_user = db.get(User, user_id)
    assert db_user is not None
    assert db_user.password_hash != plain_password
    assert db_user.password_hash.startswith("$2b$")
    assert verify_password(plain_password, db_user.password_hash) is True


def test_register_duplicate_email_fails(client: TestClient) -> None:
    """Verify registration with duplicate email returns 409 Conflict."""
    unique_email = f"duplicate_{uuid.uuid4().hex[:8]}@testauth.example.com"
    payload = {
        "name": "First User",
        "email": unique_email,
        "password": "Password123!",
    }

    resp1 = client.post("/api/v1/auth/register", json=payload)
    assert resp1.status_code == status.HTTP_201_CREATED

    resp2 = client.post("/api/v1/auth/register", json=payload)
    assert resp2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in resp2.json()["detail"]


def test_register_duplicate_email_case_insensitive(client: TestClient) -> None:
    """Verify email uniqueness check is case-insensitive."""
    base_id = uuid.uuid4().hex[:8]
    email_lower = f"case_{base_id}@testauth.example.com"
    email_upper = f"CASE_{base_id}@TESTAUTH.EXAMPLE.COM"

    resp1 = client.post(
        "/api/v1/auth/register",
        json={"name": "User One", "email": email_lower, "password": "Password123!"},
    )
    assert resp1.status_code == status.HTTP_201_CREATED

    resp2 = client.post(
        "/api/v1/auth/register",
        json={"name": "User Two", "email": email_upper, "password": "Password123!"},
    )
    assert resp2.status_code == status.HTTP_409_CONFLICT


def test_register_invalid_email_format(client: TestClient) -> None:
    """Verify registration with invalid email format returns 422."""
    payload = {
        "name": "Invalid Email",
        "email": "not-an-email",
        "password": "Password123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_register_password_too_short(client: TestClient) -> None:
    """Verify registration with password shorter than 8 characters returns 422."""
    payload = {
        "name": "Short Pwd",
        "email": f"short_{uuid.uuid4().hex[:8]}@testauth.example.com",
        "password": "short",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_register_missing_fields(client: TestClient) -> None:
    """Verify registration with missing required fields returns 422."""
    response = client.post("/api/v1/auth/register", json={"name": "Only Name"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ===========================================================================
# 3. Login Endpoint Integration Tests
# ===========================================================================
def test_login_success(client: TestClient, db: Session) -> None:
    """Verify valid credentials return 200 OK with Bearer access token."""
    email = f"login_ok_{uuid.uuid4().hex[:8]}@testauth.example.com"
    password = "ValidPassword123"
    create_test_user(db, email=email, password=password)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Verify token payload
    payload = decode_access_token(data["access_token"])
    assert "sub" in payload


def test_login_case_insensitive_email(client: TestClient, db: Session) -> None:
    """Verify login succeeds regardless of email casing."""
    base_id = uuid.uuid4().hex[:8]
    email = f"mixedcase_{base_id}@testauth.example.com"
    password = "ValidPassword123"
    create_test_user(db, email=email, password=password)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": f"MixedCase_{base_id}@TestAuth.EXAMPLE.com",
            "password": password,
        },
    )
    assert response.status_code == status.HTTP_200_OK
    assert "access_token" in response.json()


def test_login_wrong_password_fails(client: TestClient, db: Session) -> None:
    """Verify incorrect password returns 401 Unauthorized with generic message."""
    email = f"wrongpwd_{uuid.uuid4().hex[:8]}@testauth.example.com"
    create_test_user(db, email=email, password="RealPassword123")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword999"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid email or password"
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_login_nonexistent_email_fails(client: TestClient) -> None:
    """Verify non-existent email returns 401 without revealing user nonexistence."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "nobody_exists@testauth.example.com",
            "password": "AnyPassword123",
        },
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid email or password"


def test_login_invalid_body(client: TestClient) -> None:
    """Verify missing credentials in login body returns 422."""
    response = client.post("/api/v1/auth/login", json={})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ===========================================================================
# 4. Current User Profile (/api/v1/auth/me) Integration Tests
# ===========================================================================
def test_get_me_success(client: TestClient, db: Session) -> None:
    """Verify /auth/me returns the profile of the authenticated user."""
    email = f"getme_{uuid.uuid4().hex[:8]}@testauth.example.com"
    user = create_test_user(db, email=email, name="Current User Alice")

    token = create_access_token(subject=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["id"] == str(user.id)
    assert data["name"] == "Current User Alice"
    assert data["email"] == email
    assert data["role"] == "customer"
    assert "password_hash" not in data


def test_get_me_missing_token_fails(client: TestClient) -> None:
    """Verify /auth/me without Authorization header returns 401."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_get_me_invalid_token_fails(client: TestClient) -> None:
    """Verify /auth/me with invalid token returns 401."""
    headers = {"Authorization": "Bearer invalid.malformed.token"}
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid or expired" in response.json()["detail"]


def test_get_me_expired_token_fails(client: TestClient, db: Session) -> None:
    """Verify /auth/me with expired token returns 401."""
    email = f"expired_{uuid.uuid4().hex[:8]}@testauth.example.com"
    user = create_test_user(db, email=email)

    token = create_access_token(
        subject=str(user.id),
        expires_delta=timedelta(seconds=-10),
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid or expired" in response.json()["detail"]


def test_get_me_nonexistent_user_token_fails(client: TestClient) -> None:
    """Verify /auth/me with token for non-existent user returns 401."""
    fake_uuid = str(uuid.uuid4())
    token = create_access_token(subject=fake_uuid)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "does not exist" in response.json()["detail"]


# ===========================================================================
# 5. RBAC Architecture Tests (via Test-Only Router)
# ===========================================================================
def test_rbac_admin_endpoint_as_admin_allowed(client: TestClient, db: Session) -> None:
    """Verify user with ADMIN role can access admin-only endpoint."""
    admin_user = create_test_user(
        db,
        email=f"admin_{uuid.uuid4().hex[:8]}@testauth.example.com",
        role=UserRole.ADMIN,
    )
    token = create_access_token(subject=str(admin_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/test-rbac-only/admin-only", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == "admin_granted"
    assert response.json()["user_id"] == str(admin_user.id)


def test_rbac_admin_endpoint_as_customer_forbidden(
    client: TestClient, db: Session
) -> None:
    """Verify user with CUSTOMER role receives 403 Forbidden on admin endpoint."""
    customer_user = create_test_user(
        db,
        email=f"cust_{uuid.uuid4().hex[:8]}@testauth.example.com",
        role=UserRole.CUSTOMER,
    )
    token = create_access_token(subject=str(customer_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/test-rbac-only/admin-only", headers=headers)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Insufficient permissions" in response.json()["detail"]


def test_rbac_admin_endpoint_as_provider_forbidden(
    client: TestClient, db: Session
) -> None:
    """Verify user with PROVIDER role receives 403 Forbidden on admin endpoint."""
    provider_user = create_test_user(
        db,
        email=f"prov_{uuid.uuid4().hex[:8]}@testauth.example.com",
        role=UserRole.PROVIDER,
    )
    token = create_access_token(subject=str(provider_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/test-rbac-only/admin-only", headers=headers)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Insufficient permissions" in response.json()["detail"]


def test_rbac_admin_endpoint_unauthenticated(client: TestClient) -> None:
    """Verify unauthenticated request to RBAC-protected endpoint returns 401."""
    response = client.get("/test-rbac-only/admin-only")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_rbac_staff_endpoint_as_provider_allowed(
    client: TestClient, db: Session
) -> None:
    """Verify user with PROVIDER role can access multi-role staff endpoint."""
    provider_user = create_test_user(
        db,
        email=f"staffprov_{uuid.uuid4().hex[:8]}@testauth.example.com",
        role=UserRole.PROVIDER,
    )
    token = create_access_token(subject=str(provider_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/test-rbac-only/staff-only", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == "staff_granted"
    assert response.json()["role"] == "provider"


def test_rbac_staff_endpoint_as_customer_forbidden(
    client: TestClient, db: Session
) -> None:
    """Verify user with CUSTOMER role receives 403 Forbidden on staff endpoint."""
    customer_user = create_test_user(
        db,
        email=f"staffcust_{uuid.uuid4().hex[:8]}@testauth.example.com",
        role=UserRole.CUSTOMER,
    )
    token = create_access_token(subject=str(customer_user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/test-rbac-only/staff-only", headers=headers)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Insufficient permissions" in response.json()["detail"]
