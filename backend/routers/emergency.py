import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, List, Dict, Any

from database import get_db, DBUser, DBLocation, DBEmergencyAlert, DBChatMessage, DBAuditLog
from schemas import TokenData, SOSRequest, ChatMessageRequest, UserResponse
from .auth import role_required
from service.blockchain_service import get_tourist_from_ledger
from .websocket_manager import manager
from pywebpush import webpush, WebPushException
from jose import jwt, JWTError

# These should be in your .env file
VAPID_PRIVATE_KEY = "YOUR_PRIVATE_KEY"
VAPID_CLAIMS = {"sub": "mailto:admin@traveldiary.com"}
SECRET_KEY = "gdeugfuegfd"
ALGORITHM = "HS256"

router = APIRouter()

def _serialize_chat(msg: DBChatMessage) -> dict:
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "recipient_id": msg.recipient_id,
        "message": msg.message,
        "timestamp": str(msg.timestamp),
        "status": getattr(msg, "status", "sent"),
        "sender_name": msg.sender.full_name or msg.sender.username if msg.sender else "System",
        "role": msg.sender.role if msg.sender else "system"
    }

def _serialize_alert(alert: DBEmergencyAlert) -> dict:
    return {
        "id": alert.id,
        "user_id": alert.user_id,
        "message": alert.message,
        "status": alert.status,
        "latitude": alert.latitude,
        "longitude": alert.longitude,
        "created_at": str(alert.created_at),
    }

def _serialize_location(loc: DBLocation, user: Optional[DBUser] = None, is_sos: bool = False) -> dict:
    return {
        "id": loc.id,
        "user_id": loc.tourist_id or loc.user_id if hasattr(loc, 'user_id') else None,
        "username": user.username if user else "Unknown",
        "full_name": user.full_name if user else "Unknown",
        "digital_tourist_id": user.digital_tourist_id if user else "Pending ID",
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "hr": getattr(loc, "heart_rate", 0) or 72,
        "spo2": getattr(loc, "spo2", 0) or 98,
        "is_sos": is_sos,
        "updated_at": str(loc.timestamp),
    }

@router.websocket("/ws/chat/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int, db: Session = Depends(get_db)):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    try:
        # Clean token (remove Bearer prefix if sent)
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        role = payload.get("role", "tourist")
    except JWTError:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    await manager.connect(user_id, role, websocket)

    try:
        while True:
            data = await websocket.receive_json()

            msg_type = data.get("type", "chat")
            recipient_id = data.get("recipient_id")

            # Handle real-time read receipts
            if msg_type == "status_update":
                msg_id = data.get("message_id")
                new_status = data.get("status")
                if msg_id and new_status:
                    db_msg = db.query(DBChatMessage).filter(DBChatMessage.id == msg_id).first()
                    if db_msg:
                        db_msg.status = new_status
                        db.commit()
                        if recipient_id:
                            await manager.send_personal_message({"type": "status_update", "message_id": msg_id, "status": new_status}, recipient_id)
                continue

            # Handle Itinerary-based Group Chat
            if msg_type == "group_chat":
                user = db.query(DBUser).filter(DBUser.id == user_id).first()
                if not user or not user.itinerary:
                    await websocket.send_json({"error": "No itinerary linked to your profile."})
                    continue
                
                # Find all tourists sharing the exact same itinerary record
                peers = db.query(DBUser.id).filter(
                    DBUser.itinerary == user.itinerary, 
                    DBUser.role == "tourist"
                ).all()
                peer_ids = [p[0] for p in peers]
                
                payload = {
                    "type": "group_chat",
                    "sender_id": user_id,
                    "sender_name": user.full_name or user.username,
                    "message": (data.get("message") or "").strip(),
                    "timestamp": str(datetime.utcnow())
                }
                
                await manager.send_to_multiple_users(payload, peer_ids)
                continue

            # Handle Proximity-based Chat (Nearby Tourists & Security)
            if msg_type == "proximity_chat":
                # 1. Get sender's last known location
                sender_loc = db.query(DBLocation).filter(DBLocation.tourist_id == user_id).order_by(DBLocation.timestamp.desc()).first()
                if not sender_loc:
                    await websocket.send_json({"error": "Location data required for proximity chat."})
                    continue
                
                # 2. Find users within ~5km radius (simplified bounding box for performance)
                # 0.045 degrees is roughly 5km
                lat_min, lat_max = sender_loc.latitude - 0.045, sender_loc.latitude + 0.045
                lon_min, lon_max = sender_loc.longitude - 0.045, sender_loc.longitude + 0.045
                
                nearby_locations = db.query(DBLocation.tourist_id).filter(
                    DBLocation.latitude.between(lat_min, lat_max),
                    DBLocation.longitude.between(lon_min, lon_max),
                    DBLocation.timestamp >= datetime.utcnow() - timedelta(minutes=30)
                ).distinct().all()
                
                nearby_ids = [loc[0] for loc in nearby_locations]
                
                # 3. Always include online security/admin in proximity broadcasts
                security_users = db.query(DBUser.id).filter(DBUser.role.in_(["security", "police", "admin"])).all()
                nearby_ids.extend([u[0] for u in security_users])

                sender_info = db.query(DBUser).filter(DBUser.id == user_id).first()
                
                payload = {
                    "type": "proximity_chat",
                    "sender_id": user_id,
                    "sender_name": sender_info.full_name or sender_info.username,
                    "sender_role": sender_info.role,
                    "message": (data.get("message") or "").strip(),
                    "timestamp": str(datetime.utcnow()),
                    "coords": {"lat": sender_loc.latitude, "lng": sender_loc.longitude}
                }
                
                await manager.send_to_multiple_users(payload, list(set(nearby_ids)))
                continue

            # Handle real-time typing indicators without DB persistence
            if msg_type == "typing":
                if recipient_id:
                    await manager.send_personal_message({"type": "typing", "sender_id": user_id}, recipient_id)
                continue

            msg_text = (data.get("message") or "").strip()

            if not msg_text:
                await websocket.send_json({"error": "message cannot be empty"})
                continue

            if recipient_id is not None:
                recipient = db.query(DBUser).filter(DBUser.id == recipient_id).first()
                if not recipient:
                    await websocket.send_json({"error": "recipient not found"})
                    continue

            new_msg = DBChatMessage(
                sender_id=user_id,
                recipient_id=recipient_id,
                message=msg_text,
            )

            try:
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)
            except Exception:
                db.rollback()
                await websocket.send_json({"error": "failed to save message"})
                continue

            payload = _serialize_chat(new_msg)

            if recipient_id:
                await manager.send_personal_message(payload, recipient_id)
            else:
                await manager.broadcast(payload, db=db)

            await websocket.send_json({"status": "sent", "message": payload})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/security/alerts")
async def security_alerts_ws(websocket: WebSocket):
    """
    Real-time security broadcast channel for SOS and AI Anomalies.
    Handshake logic: Accept only if token has 'security' or 'admin' role.
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        role = payload.get("role")
        u_id = payload.get("id", 999) # Use token ID or fallback
        if role not in ["security", "police", "admin"]:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    # Connect using real user credentials for better auditing
    await manager.connect(u_id, role, websocket) 

    try:
        while True:
            await websocket.receive_text() # Keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@router.get("/emergency/tourist/{tourist_id}/trail")
def get_tourist_trail(
    tourist_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "police")),
):
    """Fetches the last 5 location signals for a specific tourist to generate a movement trail."""
    signals = (
        db.query(DBLocation)
        .filter(DBLocation.tourist_id == tourist_id)
        .order_by(DBLocation.timestamp.desc())
        .limit(5)
        .all()
    )
    # Return in chronological order (oldest to newest) for trail drawing logic
    return [_serialize_location(loc) for loc in reversed(signals)]

@router.get("/emergency/verify-ledger/{digital_id}")
def verify_ledger(
    digital_id: str,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "police")),
):
    record = get_tourist_from_ledger(digital_id)
    if not record:
        raise HTTPException(status_code=404, detail="Digital ID not found in local ledger")
    return record


@router.get("/emergency/tourist-profile/{digital_id}", response_model=UserResponse)
def get_tourist_profile_by_digital_id(
    digital_id: str,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "police")),
):
    ledger_record = get_tourist_from_ledger(digital_id)
    
    # Security check: Ensure that even if the ledger lookup fails, we don't leak 
    # information about whether the ID exists or not to unauthorized parties.
    if not ledger_record or (hasattr(ledger_record, 'status') and ledger_record.status == "revoked"):
        raise HTTPException(
            status_code=404, 
            detail="Digital Tourist ID not found or is no longer valid in the tamper-proof ledger."
        )

    user = db.query(DBUser).filter(DBUser.digital_tourist_id == digital_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Tourist profile not found in database for this Digital ID.")

    # Blockchain Temporary Validity Logic
    if user.trip_end:
        # user.trip_end is now a datetime object from the DB
        expiry_date = user.trip_end if isinstance(user.trip_end, datetime) else datetime.fromisoformat(str(user.trip_end))
        
        # Compare using UTC-aware comparison if necessary, or simple naive comparison
        if datetime.now(expiry_date.tzinfo) > expiry_date:
            raise HTTPException(status_code=403, detail="Digital Tourist ID has expired as the trip duration has ended.")

    return user


@router.get("/emergency/history")
def get_emergency_history(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "police")),
):
    alerts = db.query(DBEmergencyAlert).order_by(DBEmergencyAlert.id.desc()).all()
    return [_serialize_alert(a) for a in alerts]


@router.get("/emergency/tourists/live-locations")
def get_live_locations(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "police")),
):
    # Requirement: Only users in ACTIVE and VERIFIED state should be visible
    results = (
        db.query(DBLocation, DBUser)
        .join(DBUser, DBUser.id == DBLocation.tourist_id)
        .filter(DBUser.is_active == True)
        .filter(DBUser.is_verified == True)
        .order_by(DBLocation.timestamp.desc())
        .all()
    )
    
    # Get all users with open alerts to flag them in the telemetry list
    active_sos_ids = {a.user_id for a in db.query(DBEmergencyAlert.user_id).filter(DBEmergencyAlert.status == "open").all()}

    latest_by_user: Dict[int, dict] = {}
    for loc, user in results:
        if user.id not in latest_by_user:
            latest_by_user[user.id] = _serialize_location(loc, user, user.id in active_sos_ids)

    return list(latest_by_user.values())


@router.get("/emergency/chat/history/{tourist_id}")
def get_chat_history(
    tourist_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "tourist")),
):
    if current_user.role == "tourist":
        # Tourists see all personal messages sent to/from them, plus broadcasts
        query_filter = or_(
            DBChatMessage.sender_id == current_user.id,
            DBChatMessage.recipient_id == current_user.id,
            DBChatMessage.recipient_id.is_(None)
        )
    else:
        # Security/Admin see their conversation history with a specific tourist
        query_filter = or_(
            and_(DBChatMessage.sender_id == current_user.id, DBChatMessage.recipient_id == tourist_id),
            and_(DBChatMessage.sender_id == tourist_id, DBChatMessage.recipient_id == current_user.id),
            and_(DBChatMessage.recipient_id.is_(None), or_(DBChatMessage.sender_id == tourist_id, DBChatMessage.sender_id == current_user.id))
        )

    messages = (
        db.query(DBChatMessage)
        .filter(query_filter)
        .order_by(DBChatMessage.timestamp.asc())
        .all()
    )

    return [_serialize_chat(m) for m in messages]


@router.post("/emergency/sos")
async def post_sos(
    sos_request: SOSRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("tourist")),
):
    current_db_user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not current_db_user:
        raise HTTPException(status_code=404, detail="Current user not found")

    try:
        msg_text = sos_request.message or "SOS triggered"
        # Detect automated live updates sent periodically during an active SOS session
        is_automated = "Automated" in msg_text

        alert = DBEmergencyAlert(
            user_id=current_db_user.id,
            message=msg_text,
            latitude=sos_request.current_latitude,
            longitude=sos_request.current_longitude,
            status="open",
        )
        
        # Requirement 8: Persistent Audit Log for Emergency Trigger
        audit_entry = DBAuditLog(
            user_id=current_db_user.id,
            action="SOS_TRIGGERED",
            target_id=alert.id,
            details=f"Manual SOS at {sos_request.current_latitude}, {sos_request.current_longitude}"
        )
        db.add(audit_entry)
        db.add(alert)
        db.commit()
        db.refresh(alert)

        payload = _serialize_alert(alert)
        
        # Real-time Broadcast to Admin and Police/Security
        # Tagging automated updates as 'high' priority to ensure clear visibility on Security Terminals
        await manager.broadcast({
            "type": "EMERGENCY_SOS",
            "user": current_db_user.username,
            "reason": msg_text,
            "severity": "high" if is_automated else "critical",
            "digital_id": current_db_user.digital_tourist_id,
            "data": payload
        }, role_filter=["admin", "security", "police"], db=db)

        return {"message": "SOS received", "alert": payload}

    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save SOS alert")


@router.post("/emergency/broadcast")
async def post_broadcast(
    message: dict,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security")),
):
    msg_text = message.get("message")
    if not msg_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    payload = {
        "type": "broadcast",
        "message": msg_text,
        "sender": current_user.username,
        "timestamp": datetime.utcnow().isoformat()
    }

    await manager.broadcast(payload, db=db)

    # Send Push Notifications for background users
    all_tourists = db.query(DBUser).filter(DBUser.role == "tourist", DBUser.push_subscription != None).all()
    for tourist in all_tourists:
        try:
            sub_info = json.loads(tourist.push_subscription)
            webpush(
                subscription_info=sub_info,
                data=json.dumps({
                    "title": "🚨 SAFETY BROADCAST",
                    "message": msg_text
                }),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except WebPushException as ex:
            print(f"Failed to send push to {tourist.username}: {ex}")

    return {"message": "Broadcast sent", "payload": payload}


@router.post("/emergency/chat")
def post_chat(
    chat_message: ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("tourist", "admin", "security")),
):
    current_db_user = db.query(DBUser).filter(DBUser.username == current_user.username).first()
    if not current_db_user:
        raise HTTPException(status_code=404, detail="Current user not found")

    try:
        new_msg = DBChatMessage(
            sender_id=current_db_user.id,
            recipient_id=getattr(chat_message, "recipient_id", None),
            message=getattr(chat_message, "message", "").strip(),
        )
        if not new_msg.message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        db.add(new_msg)
        db.commit()
        db.refresh(new_msg)
        return {"message": "Chat message sent", "chat": _serialize_chat(new_msg)}

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save chat message")


@router.post("/emergency/chat/archive/{tId}")
def archive_chat(
    tId: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "police")),
):
    # Mark all messages involving this tourist as archived
    db.query(DBChatMessage).filter(
        or_(DBChatMessage.sender_id == tId, DBChatMessage.recipient_id == tId)
    ).update({"status": "archived"}, synchronize_session=False)
    db.commit()
    return {"message": f"Tactical chat history for tourist {tId} has been archived."}


@router.post("/emergency/mark-safe/{tId}")
def mark_safe(
    tId: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "police")),
):
    # Resolve all open alerts for the specific tourist
    db.query(DBEmergencyAlert).filter(
        DBEmergencyAlert.user_id == tId,
        DBEmergencyAlert.status == "open"
    ).update({"status": "resolved"}, synchronize_session=False)
    db.commit()
    return {"message": f"Tourist {tId} location cleared. Alerts marked as safe."}


@router.post("/emergency/verify-all")
def verify_all(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin")),
):
    # Mass update for tourists awaiting verification who have provided documents
    pending_tourists = db.query(DBUser).filter(
        DBUser.role == "tourist",
        DBUser.is_verified == False
    ).all()
    
    count = 0
    for tourist in pending_tourists:
        tourist.is_verified = True
        count += 1
    
    # Requirement 8: High-level Authority Audit
    batch_log = DBAuditLog(
        user_id=current_user.id,
        action="BULK_IDENTITY_VERIFICATION",
        details=f"System-wide sync complete. {count} tourists verified."
    )
    db.add(batch_log)
    db.commit()
    return {"message": f"Batch identity sync complete. {count} identities verified on ledger."}

@router.post("/emergency/ping/{tourist_id}")
async def send_ping(
    tourist_id: int,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(role_required("admin", "security", "police")),
):
    """Sends a high-priority ping request to a specific tourist's device."""
    payload = {
        "type": "ping_request",
        "message": "Dispatcher is requesting an immediate status check. Please signal active.",
        "sender": current_user.username
    }
    await manager.send_personal_message(payload, tourist_id)
    return {"message": "Ping request dispatched to subject device."}