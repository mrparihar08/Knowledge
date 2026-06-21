import logging
import random
import string
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db, DBUser
from schemas import RejectionRequest
from routers.auth import role_required, TokenData
from service.blockchain_service import record_tourist_id_on_chain

router = APIRouter()
logger = logging.getLogger(__name__)


def _dob_to_str(dob_value) -> str:
    """
    Accepts either:
    - datetime/date object
    - string in YYYY-MM-DD format
    """
    if isinstance(dob_value, date):
        return dob_value.strftime("%Y-%m-%d")

    if isinstance(dob_value, str):
        return dob_value

    raise HTTPException(status_code=400, detail="Invalid date of birth format.")


def generate_tourist_id_logic(user: DBUser, db: Session) -> str:
    """
    Generate a unique Digital Tourist ID.

    Format:
    [Country Code (2)][DOB MMYY (4)][Surname (3)][3-digit Series (3)][2 Alphabets (2)]
    Example:
    IN1020RAM999AA
    """
    cc = (user.nationality or "IN")[:2].upper().ljust(2, "X")

    try:
        dob_str = _dob_to_str(user.dob)
        dt_obj = datetime.strptime(dob_str, "%Y-%m-%d")
        mmyy = dt_obj.strftime("%m%y")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format for user {user.username}. Expected YYYY-MM-DD.",
        )

    name_parts = (user.full_name or "Tourist").split()
    # Target the last part of the name for Surname logic
    surname_raw = name_parts[-1] if name_parts else "XXX"
    surname = "".join(filter(str.isalpha, surname_raw))[:3].upper().ljust(3, "X")

    # Generate a random 3-digit series for the specific trip record
    for _ in range(20):
        series = str(random.randint(100, 999))
        alpha = "".join(random.choices(string.ascii_uppercase, k=2))
        digital_id = f"{cc}{mmyy}{surname}{series}{alpha}"

        exists = (
            db.query(DBUser.id)
            .filter(DBUser.digital_tourist_id == digital_id)
            .first()
        )
        if not exists:
            return digital_id

    raise HTTPException(
        status_code=500,
        detail="Failed to generate a unique Digital Tourist ID.",
    )


def _safe_record_on_chain(digital_id: str):
    """
    Runs in background. Errors are logged but not returned to the API client.
    """
    try:
        record_tourist_id_on_chain(digital_id)
        logger.info("Recorded tourist ID on chain: %s", digital_id)
    except Exception as exc:
        logger.exception("Blockchain registration failed for %s: %s", digital_id, exc)


@router.get("/verifier/tourists/pending")
def get_pending_tourists(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("verifier", "admin")),
):
    rows = (
        db.query(
            DBUser.id,
            DBUser.full_name,
            DBUser.username,
            DBUser.document_path,
            DBUser.identity_number,
            DBUser.nationality,
            DBUser.dob,
            DBUser.trip_start,
            DBUser.trip_end,
            DBUser.itinerary
        )
        .filter(
            DBUser.role == "tourist",
            DBUser.is_verified.is_(False),
            DBUser.document_path.isnot(None),
        )
        .all()
    )

    return [
        {
            "id": row.id,
            "name": row.full_name,
            "username": row.username,
            "doc": row.document_path,
            "id_number": row.identity_number,
            "nationality": row.nationality,
            "dob": str(row.dob),
            "trip_start": str(row.trip_start),
            "trip_end": str(row.trip_end),
            "itinerary": row.itinerary
        }
        for row in rows
    ]


@router.post("/verifier/approve/{user_id}")
def approve_kyc(
    user_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("verifier", "admin")),
):
    user = (
        db.query(DBUser)
        .filter(DBUser.id == user_id, DBUser.role == "tourist")
        .first()
    )

    if not user:
        raise HTTPException(status_code=404, detail="Tourist not found")

    if user.is_verified:
        return {"message": f"Tourist {user.username} is already verified."}

    try:
        new_digital_id = generate_tourist_id_logic(user, db)

        user.is_verified = True
        user.digital_tourist_id = new_digital_id
        user.rejection_reason = None

        db.commit()
        db.refresh(user)

        background_tasks.add_task(_safe_record_on_chain, new_digital_id)

        return {
            "message": f"Tourist {user.username} approved successfully.",
            "digital_tourist_id": new_digital_id,
            "blockchain_status": "Queued for on-chain registration",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to approve KYC for user_id=%s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Failed to approve tourist")


@router.post("/verifier/reject/{user_id}")
def reject_kyc(
    user_id: int,
    rejection: RejectionRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("verifier", "admin")),
):
    user = (
        db.query(DBUser)
        .filter(DBUser.id == user_id, DBUser.role == "tourist")
        .first()
    )

    if not user:
        raise HTTPException(status_code=404, detail="Tourist not found")

    try:
        user.is_verified = False
        user.rejection_reason = rejection.reason
        user.digital_tourist_id = None

        db.commit()
        db.refresh(user)

        return {
            "message": f"Tourist {user.username} rejected.",
            "reason": rejection.reason,
        }

    except Exception as exc:
        db.rollback()
        logger.exception("Failed to reject KYC for user_id=%s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Failed to reject tourist")