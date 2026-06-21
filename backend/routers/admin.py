from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict
from database import get_db, DBUser, DBEmergencyAlert
from .auth import role_required, TokenData
from datetime import datetime
from .websocket_manager import manager
from routers.ai_logic import check_system_wide_inactivity

router = APIRouter(prefix="/admin", tags=["admin"])

# Note: In a production environment, DBAuditLog would be a formal SQLAlchemy model.
def log_security_event(db: Session, user: str, action: str, target: str):
    """Helper to simulate secure audit logging for compliance."""
    # Example: db_log = DBAuditLog(user=user, action=action, target=target, timestamp=datetime.utcnow())
    print(f"AUDIT LOG: [{datetime.utcnow()}] {user} performed {action} on {target}")

@router.get("/stats")
def get_admin_stats(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin"))
):
    active_tourists = db.query(DBUser).filter(DBUser.role == "tourist", DBUser.is_verified == True).count()
    pending_kyc = db.query(DBUser).filter(DBUser.role == "tourist", DBUser.is_verified == False, DBUser.document_path != None).count()
    open_alerts = db.query(DBEmergencyAlert).filter(DBEmergencyAlert.status == "open").count()
    
    return {
        "active_tourists": active_tourists,
        "pending_kyc": pending_kyc,
        "open_alerts": open_alerts,
        "verifiers_online": 5 # Placeholder for real-time connection tracking
    }

@router.get("/audit-logs")
def get_audit_logs(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin"))
):
    # This would typically query a DBAuditLog table
    return [
        {"id": 1, "user": "verifier_01", "action": "Approved KYC", "target": "Tourist_102", "timestamp": str(datetime.now())},
        {"id": 2, "user": "admin_main", "action": "Escalated SOS", "target": "Alert_55", "timestamp": str(datetime.now())}
    ]

@router.post("/efir/generate/{alert_id}")
def generate_efir(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin"))
):
    alert = db.query(DBEmergencyAlert).filter(DBEmergencyAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    # Logic to generate a unique E-FIR number and store it
    efir_no = f"EFIR-{datetime.now().strftime('%Y%m%d')}-{alert_id:04d}"
    alert.status = "investigating" # Update status
    
    log_security_event(db, current_user.username, "Generated E-FIR", f"Alert {alert_id}")
    db.commit()
    
    return {"message": "E-FIR generated successfully", "efir_number": efir_no}

@router.post("/escalate/{alert_id}")
async def escalate_to_police(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin"))
):
    alert = db.query(DBEmergencyAlert).filter(DBEmergencyAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    await manager.broadcast({
        "type": "POLICE_ESCALATION",
        "alert_id": alert_id,
        "priority": "CRITICAL"
    }, role_filter=["security"], db=db)

    log_security_event(db, current_user.username, "Escalated SOS to Police", f"Alert {alert_id}")

    return {"message": f"Alert {alert_id} escalated to local security forces."}

@router.patch("/verifiers/{verifier_id}/status")
def toggle_verifier_access(
    verifier_id: int,
    is_active: bool,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin"))
):
    verifier = db.query(DBUser).filter(DBUser.id == verifier_id, DBUser.role == "verifier").first()
    if not verifier:
        raise HTTPException(status_code=404, detail="Verifier not found")
    
    verifier.is_verified = is_active
    db.commit()

    log_security_event(db, current_user.username, "Toggled Verifier Status", f"Verifier {verifier.username} (Active={is_active})")
    
    return {"message": f"Verifier {verifier.username} status updated to {'Active' if is_active else 'Suspended'}"}

@router.post("/ai/trigger-scan")
async def trigger_ai_safety_scan(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin"))
):
    """Manual trigger for AI to scan for inactive or disappeared tourists."""
    anomalies = check_system_wide_inactivity(db)
    
    for anomaly in anomalies:
        await manager.broadcast({
            "type": "AI_PREDICTIVE_ALERT",
            "data": anomaly
        }, role_filter=["admin", "security"], db=db)
    
    log_security_event(db, current_user.username, "Triggered Manual AI Safety Scan", "System-Wide")

    return {"message": f"Scan complete. Found {len(anomalies)} anomalies.", "details": anomalies}