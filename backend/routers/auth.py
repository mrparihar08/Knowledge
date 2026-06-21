import os
import uuid
import shutil
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db, DBUser
from schemas import (
    Token,
    TokenData,
    UserSignup,
    UserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ProfileUpdateResponse,
    ChangePasswordRequest,
)

router = APIRouter()

logger = logging.getLogger(__name__)

# --- Security Configuration ---
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "generate-a-long-random-string-at-least-32-chars")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
RESET_TOKEN_EXPIRE_HOURS = 1

PROFILE_DIR = "uploads/profiles"
os.makedirs(PROFILE_DIR, exist_ok=True)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


# --- Security Helpers ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_reset_token(email: str):
    expire = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": email, "exp": expire, "type": "reset"},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def verify_reset_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "reset":
            raise JWTError("Invalid token type")
        email = payload.get("sub")
        if not email:
            raise JWTError("Invalid token payload")
        return email
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role")
        user_id = payload.get("id")
        token_type = payload.get("type")

        if token_type != "access":
            raise credentials_exception

        if not username:
            raise credentials_exception

        return TokenData(username=username, role=role, id=user_id)
    except JWTError:
        raise credentials_exception


def role_required(*allowed_roles: str):
    def role_checker(current_user: TokenData = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return role_checker


# --- Endpoints ---
@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
def signup_user(user_data: UserSignup, db: Session = Depends(get_db)):
    existing_user = db.query(DBUser).filter(DBUser.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    existing_email = db.query(DBUser).filter(DBUser.email == user_data.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    existing_phone = db.query(DBUser).filter(DBUser.phone_number == user_data.phone_number).first()
    if existing_phone:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    # Ensure empty suggested IDs from non-tourist roles are stored as NULL to avoid unique constraint collisions
    actual_tourist_id = user_data.suggested_id if user_data.suggested_id and user_data.suggested_id.strip() else None

    new_user = DBUser(
        username=user_data.username,
        hashed_password=pwd_context.hash(user_data.password),
        email=user_data.email,
        phone_number=user_data.phone_number,
        role=user_data.role,
        full_name=user_data.full_name,
        dob=user_data.dob,
        digital_tourist_id=actual_tourist_id,
        is_verified=False,
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except Exception as e:
        db.rollback()
        logger.error(f"Database error during user signup: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create user")

    return {"message": "User created successfully. Please login to upload documents."}


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(DBUser).filter(DBUser.username == form_data.username).first()

    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "id": user.id}
    )
    return {"access_token": access_token, "token_type": "bearer", "user_role": user.role}


@router.get("/users/me", response_model=UserResponse)
def get_me(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/profile/edit", response_model=ProfileUpdateResponse)
async def update_profile(
    name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    profile_pic: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        if name is not None:
            cleaned_name = name.strip()
            if cleaned_name:
                user.full_name = cleaned_name

        if bio is not None:
            user.bio = bio.strip()

        if email is not None:
            new_email = email.strip()
            if new_email and new_email != user.email:
                existing = db.query(DBUser).filter(DBUser.email == new_email).first()
                if existing:
                    raise HTTPException(status_code=400, detail="Email already taken")
                user.email = new_email

        if profile_pic:
            file_ext = os.path.splitext(profile_pic.filename or "")[1].lower()
            if file_ext not in [".jpg", ".jpeg", ".png"]:
                raise HTTPException(status_code=400, detail="Invalid image format")

            file_name = f"{uuid.uuid4().hex}{file_ext}"
            file_path = os.path.join(PROFILE_DIR, file_name)

            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(profile_pic.file, buffer)

            user.profile_pic = file_path

        db.commit()
        db.refresh(user)

        return {
            "message": "Profile updated successfully",
            "user": user,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update profile")


@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.email == request.email).first()

    if user:
        reset_token = create_reset_token(user.email)

        # In production: send this token/link by email instead of printing.
        # Example reset URL:
        # f"{FRONTEND_URL}/reset-password?token={reset_token}"
        print(f"DEBUG reset token for {user.email}: {reset_token}")

    return {"message": "If an account exists with this email, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    # Assumption: ResetPasswordRequest has fields:
    #   token: str
    #   new_password: str
    email = verify_reset_token(request.token)

    user = db.query(DBUser).filter(DBUser.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        user.hashed_password = pwd_context.hash(request.new_password)
        db.commit()
        return {"message": "Password reset successfully"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to reset password")


@router.post("/profile/change-password")
async def change_password(
    request: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not user or not pwd_context.verify(request.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password",
        )

    user.hashed_password = pwd_context.hash(request.new_password)
    db.commit()
    return {"message": "Password updated successfully"}