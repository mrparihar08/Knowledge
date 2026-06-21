import math
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import DBUser, DBLocation

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance between two points on the earth."""
    R = 6371  # Radius of earth in kilometers
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2) * math.sin(dLat / 2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dLon / 2) * math.sin(dLon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def detect_anomalies(user: DBUser, current_lat: float, current_lon: float, db: Session):
    anomalies = []
    
    # 1. Entry into Unsafe Zones (Geo-fencing)
    # Example: Defined unsafe coordinates for Northeast regions
    UNSAFE_ZONES = [
        {"name": "Restricted Border Area A", "lat": 27.123, "lon": 92.456, "radius": 5.0},
        {"name": "High Risk Forest Zone B", "lat": 26.789, "lon": 93.123, "radius": 10.0}
    ]
    
    for zone in UNSAFE_ZONES:
        dist = haversine(current_lat, current_lon, zone["lat"], zone["lon"])
        if dist <= zone["radius"]:
            anomalies.append({
                "type": "UNSAFE_ZONE_ENTRY",
                "severity": "critical",
                "reason": f"Tourist entered {zone['name']} (Distance: {dist:.2f}km)"
            })

    # 2. Route Deviation Tracking
    # Assumes itinerary contains strings with location names or coordinates
    # For this implementation, we check if the user is significantly far from their last recorded "safe" location
    last_loc = db.query(DBLocation).filter(DBLocation.tourist_id == user.id).order_by(DBLocation.timestamp.desc()).offset(1).first()
    if last_loc:
        movement_dist = haversine(current_lat, current_lon, last_loc.latitude, last_loc.longitude)
        # If moving faster than 150km/h or jumping 50km in minutes, flag anomaly
        if movement_dist > 50.0:
            anomalies.append({
                "type": "ROUTE_DEVIATION",
                "severity": "high",
                "reason": f"Sudden large-scale movement detected: {movement_dist:.2f}km jump."
            })

    return anomalies

def check_system_wide_inactivity(db: Session):
    """Logic to find tourists who haven't updated in X hours."""
    threshold = datetime.utcnow() - timedelta(minutes=30)
    inactive_tourists = []
    
    # Subquery for latest location
    active_users = db.query(DBUser).filter(DBUser.role == "tourist", DBUser.is_verified == True).all()
    
    for user in active_users:
        last_ping = db.query(DBLocation).filter(DBLocation.tourist_id == user.id).order_by(DBLocation.timestamp.desc()).first()
        
        if not last_ping or last_ping.timestamp < threshold:
            time_diff = (datetime.utcnow() - last_ping.timestamp.replace(tzinfo=None)).total_seconds() / 60 if last_ping else 999
            
            # Detect "Sudden Disappearance" vs "Long Inactivity"
            anomaly_type = "SUDDEN_DISAPPEARANCE" if time_diff < 120 else "LONG_INACTIVITY"
            
            inactive_tourists.append({
                "user": user.username,
                "type": anomaly_type,
                "severity": "high" if anomaly_type == "SUDDEN_DISAPPEARANCE" else "medium",
                "reason": f"No signal received for {int(time_diff)} minutes.",
                "last_coords": [last_ping.latitude, last_ping.longitude] if last_ping else None
            })
            
    return inactive_tourists