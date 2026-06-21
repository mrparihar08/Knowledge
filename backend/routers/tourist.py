import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.orm import Session

from database import get_db, DBUser, DBLocation
from schemas import LocationUpdate
from .websocket_manager import manager
from .ai_logic import detect_anomalies
from .auth import role_required, TokenData

router = APIRouter()

UPLOAD_DIR = Path("uploads/documents")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}


def parse_itinerary(value: str):
    value = (value or "").strip()
    if not value:
        return []

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [item.strip() for item in value.split(",") if item.strip()]


def save_upload_file(upload_file: UploadFile) -> str:
    suffix = Path(upload_file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format in {upload_file.filename}. Use JPG, PNG or PDF.",
        )

    file_name = f"kyc_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{suffix.lstrip('.')}"
    file_name = f"{file_name}{suffix}"
    file_path = UPLOAD_DIR / file_name

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

    return str(file_path)


def cleanup_files(paths: list[str]) -> None:
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


@router.post("/tourist/upload-kyc")
def upload_kyc(
    full_name: str = Form(...),
    dob: str = Form(...),
    nationality: str = Form(...),
    identity_type: str = Form(...),
    identity_number: str = Form(...),
    emergency_contact: str = Form(...),
    itinerary: str = Form(...),
    trip_start: str = Form(...),
    trip_end: str = Form(...),
    document_files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("tourist")),
):
    user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not document_files:
        raise HTTPException(status_code=400, detail="At least one document file is required")

    try:
        datetime.strptime(dob, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Date of Birth must be in YYYY-MM-DD format.",
        )

    saved_paths: list[str] = []

    try:
        for doc in document_files:
            saved_paths.append(save_upload_file(doc))

        user.full_name = full_name.strip()
        user.dob = dob
        user.nationality = nationality.strip()
        user.identity_type = identity_type.strip()
        user.identity_number = identity_number.strip()
        user.emergency_contact = emergency_contact.strip()
        
        try:
            user.trip_start = datetime.strptime(trip_start, "%Y-%m-%d") if trip_start else None
            user.trip_end = datetime.strptime(trip_end, "%Y-%m-%d") if trip_end else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Trip start and end dates must be in YYYY-MM-DD format.")

        # If DBUser.itinerary is a JSON column, keep this as a Python list.
        # If it is a plain TEXT column, change this to json.dumps(parse_itinerary(itinerary)).
        user.itinerary = parse_itinerary(itinerary)

        # Store uploaded document paths.
        # If DBUser.document_path is a JSON column, you may want to store the list directly instead.
        user.document_path = json.dumps(saved_paths)

        if hasattr(user, "is_verified"):
            user.is_verified = False
            
        user.rejection_reason = None

        db.commit()
        db.refresh(user)

        # Requirement: Immediately notify dispatch that a new tourist has activated their profile
        import asyncio
        asyncio.create_task(manager.broadcast({
            "type": "location_update",
            "tourist_id": user.id,
            "username": user.username,
        }, role_filter=["admin", "security", "police"], db=db))

        return {"message": "KYC documents submitted successfully. Verification is pending."}

    except HTTPException:
        db.rollback()
        cleanup_files(saved_paths)
        raise
    except Exception as e:
        db.rollback()
        cleanup_files(saved_paths)
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        for doc in document_files:
            try:
                awaitable_close = doc.close()
                if hasattr(awaitable_close, "__await__"):
                    import asyncio
                    asyncio.create_task(awaitable_close)
            except Exception:
                pass


@router.post("/tourist/update-location")
async def update_location(
    location_data: LocationUpdate,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("tourist")),
):
    user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        location_row = DBLocation(
            tourist_id=user.id,
            latitude=location_data.current_latitude,
            longitude=location_data.current_longitude,
            heart_rate=location_data.heart_rate,
            spo2=location_data.spo2,
        )
        
        db.add(location_row)
        db.commit()
        db.refresh(location_row)

        # Real AI Anomaly Detection
        detected_anomalies = detect_anomalies(user, location_data.current_latitude, location_data.current_longitude, db)
        
        for anomaly in detected_anomalies:
            await manager.broadcast({
                "type": "AI_ANOMALY",
                "severity": anomaly["severity"],
                "reason": anomaly["reason"],
                "tourist": user.username,
                "anomaly_type": anomaly["type"],
                "coords": [location_data.current_latitude, location_data.current_longitude]
            }, role_filter=["admin", "security", "police"], db=db)

        payload = {
            "type": "location_update",
            "tourist_id": user.id,
            "username": user.username,
            "latitude": location_data.current_latitude,
            "longitude": location_data.current_longitude,
        }

        await manager.broadcast(payload, role_filter=["admin", "security", "police"], db=db)

        return {"message": "Location updated successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update location: {str(e)}")

@router.post("/tourist/signal-active")
async def signal_active(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("tourist")),
):
    """
    Manual 'Active' heartbeat for tourists to signal they are safe and update 
    their status on the Police Dashboard without necessarily moving.
    """
    user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Create a location entry with the last known coordinates to refresh the timestamp
    heartbeat = DBLocation(
        tourist_id=user.id,
        latitude=0.0, # Defaulting to 0 since cache is missing
        longitude=0.0,
        heart_rate=72, # Baseline vitals for heartbeat
        spo2=98
    )
    
    db.add(heartbeat)
    db.commit()

    # Notify the dashboard via WebSocket immediately
    await manager.broadcast({
        "type": "location_update",
        "tourist_id": user.id,
        "username": user.username,
    }, role_filter=["admin", "security", "police"], db=db)

    return {"message": "Signal detected by dispatch."}

@router.post("/tourist/toggle-active")
async def toggle_active_status(
    active: bool,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("tourist")),
):
    """Explicitly toggle the tourist's active status for police tracking."""
    user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    is_verified = getattr(user, "is_verified", False)
    if not is_verified and active:
        raise HTTPException(status_code=403, detail="Verification required to go active.")

    if hasattr(user, "is_active"):
        user.is_active = active
        
    db.commit()
    
    # Notify dashboard to add/remove marker immediately
    await manager.broadcast({
        "type": "location_update",
        "tourist_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "is_active": active if hasattr(user, "is_active") else True
    }, role_filter=["admin", "security", "police"], db=db)

    return {"is_active": getattr(user, "is_active", active)}