from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db, DBUser, DBLocation, DBEmergencyAlert
from .websocket_manager import manager
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List

router = APIRouter(prefix="/iot", tags=["IoT"])

class IoTDataPayload(BaseModel):
    digital_id: str
    current_latitude: float
    current_longitude: float
    heart_rate: int
    spo2: int
    sos_pressed: bool = False

@router.post("/telemetry")
async def receive_iot_data(payload: IoTDataPayload, db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.digital_tourist_id == payload.digital_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Device not linked to a verified tourist")

    # 1. Update Location
    new_loc = DBLocation(
        tourist_id=user.id, 
        latitude=payload.current_latitude, 
        longitude=payload.current_longitude,
        heart_rate=payload.heart_rate,
        spo2=payload.spo2
    )
    
    db.add(new_loc)

    # 2. Check Health Anomalies
    health_alert = None
    if payload.heart_rate > 120 or payload.heart_rate < 40 or payload.spo2 < 90:
        health_alert = f"Critical Vitals: HR {payload.heart_rate}, SpO2 {payload.spo2}%"

    # 3. Trigger SOS if button pressed or health is critical
    if payload.sos_pressed or health_alert:
        alert = DBEmergencyAlert(
            user_id=user.id,
            message=health_alert if health_alert else "IoT Device SOS Button Pressed",
            latitude=payload.current_latitude,
            longitude=payload.current_longitude,
            status="open"
        )
        db.add(alert)
        
        await manager.broadcast({
            "type": "EMERGENCY_SOS",
            "subtype": "IOT_TRIGGERED",
            "user": user.username,
            "health_data": {"hr": payload.heart_rate, "spo2": payload.spo2},
            "data": {"message": alert.message, "latitude": alert.latitude, "longitude": alert.longitude}
        }, role_filter=["admin", "security", "police"], db=db)

    db.commit()
    return {
        "status": "received",
        "alert_triggered": payload.sos_pressed or health_alert is not None
    }

@router.get("/history/{tourist_id}")
async def get_health_history(tourist_id: int, db: Session = Depends(get_db)):
    six_hours_ago = datetime.utcnow() - timedelta(hours=6)
    
    history = (
        db.query(DBLocation)
        .filter(
            DBLocation.tourist_id == tourist_id,
            DBLocation.updated_at >= six_hours_ago
        )
        .order_by(DBLocation.updated_at.desc())
        .all()
    )
    
    return [
        {"timestamp": str(h.updated_at), "hr": getattr(h, "heart_rate", 72), "spo2": getattr(h, "spo2", 98)}
        for h in history
    ]