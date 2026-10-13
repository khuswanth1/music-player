import re
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel

PASSWORD_MIN = 10
MIN_AGE = 13
Gender = Literal["man", "woman", "non_binary", "something_else", "prefer_not_to_say"]


def _validate_password(value: str) -> str:
    """Same rules the sign-up form shows: 10+ characters, a letter, and a number or special character."""
    if len(value) < PASSWORD_MIN:
        raise ValueError(f"Password must be at least {PASSWORD_MIN} characters")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters")
    if not re.search(r"[^\W\d_]", value):
        raise ValueError("Password must contain at least 1 letter")
    if not re.search(r"[\d\W_]", value):
        raise ValueError("Password must contain at least 1 number or special character")
    return value


def _validate_birth_date(value: date | None) -> date | None:
    if value is None:
        return value
    today = date.today()
    age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    if value > today or age > 120:
        raise ValueError("Enter a valid date of birth")
    if age < MIN_AGE:
        raise ValueError(f"You must be at least {MIN_AGE} to create an account")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = Field(min_length=1, max_length=80)
    date_of_birth: date | None = None
    gender: Gender | None = None
    marketing_emails: bool = Field(True, description="False when the user opts out of marketing email")

    _pw = field_validator("password")(_validate_password)
    _dob = field_validator("date_of_birth")(_validate_birth_date)

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Display name cannot be blank")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LoginCodeRequest(BaseModel):
    email: EmailStr


class LoginCodeVerify(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$", description="The 6-digit code from the email")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str

    _pw = field_validator("new_password")(_validate_password)


class ChangePasswordRequest(BaseModel):
    current_password: str | None = None  # absent for OAuth-only accounts setting a first password
    new_password: str

    _pw = field_validator("new_password")(_validate_password)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    email: EmailStr | None = None


class UserPublic(ORMModel):
    id: uuid.UUID
    display_name: str
    avatar_url: str | None


class UserMe(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str
    avatar_url: str | None
    role: str
    permissions: list[str]
    is_premium: bool
    has_password: bool
    google_linked: bool
    created_at: datetime
    date_of_birth: date | None = None
    gender: Gender | None = None
    marketing_emails: bool = True
    preferred_languages: list[str] = []


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserMe


class AuthProviders(BaseModel):
    password: bool = True
    google: bool
