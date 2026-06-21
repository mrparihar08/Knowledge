import shutil
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from database import get_db, DBUser
from routers.auth import role_required, TokenData

router = APIRouter()

UPLOAD_DIR = Path("uploads/profiles")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.put("/edit")
async def edit_profile(
    name: str = Form(None),
    email: str = Form(None),
    bio: str = Form(None),
    profile_pic: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("tourist", "admin", "security", "verifier"))
):
    user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if name is not None:
        user.full_name = name.strip()
    if email is not None:
        user.email = email.strip()
    if bio is not None:
        user.bio = bio.strip()

    if profile_pic:
        suffix = Path(profile_pic.filename or "").suffix.lower()
        if suffix not in [".jpg", ".jpeg", ".png"]:
            raise HTTPException(status_code=400, detail="Unsupported image format. Use JPG or PNG.")

        # Create a unique filename to prevent overwrites
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        file_name = f"profile_{user.id}_{timestamp}{suffix}"
        file_path = UPLOAD_DIR / file_name

        with file_path.open("wb") as buffer:
            shutil.copyfileobj(profile_pic.file, buffer)

        # Save the path using forward slashes for web compatibility
        user.profile_pic = str(file_path).replace("\\", "/")

    db.commit()
    db.refresh(user)
    return {"message": "Profile updated successfully", "user": user}