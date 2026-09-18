from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole
from app.modules.audit import service as audit

router = APIRouter(prefix="/auth", tags=["auth"])

SELF_REGISTER_ROLES = (UserRole.physician, UserRole.patient, UserRole.clinic)


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.physician


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str
    role: UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, db: DbSession, request: Request) -> User:
    if data.role not in SELF_REGISTER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This role cannot be self-registered")
    email = data.email.lower()
    if await db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, hashed_password=hash_password(data.password), full_name=data.full_name, role=data.role)
    db.add(user)
    await db.flush()
    await audit.record(
        db, action="user.register", resource_type="user", resource_id=user.id, actor_id=user.id, request=request
    )
    return user


@router.post("/token", response_model=Token)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession, request: Request) -> Token:
    user = await db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None or not user.is_active or not verify_password(form.password, user.hashed_password):
        await audit.record(db, action="auth.login_failed", resource_type="user", request=request)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password", headers={"WWW-Authenticate": "Bearer"}
        )
    await audit.record(
        db, action="auth.login", resource_type="user", resource_id=user.id, actor_id=user.id, request=request
    )
    return Token(access_token=create_access_token(user.id, user.role.value))


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user
