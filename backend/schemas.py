from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Any

class TokenData(BaseModel):
    """Schema for data stored in the JWT token."""
    username: Optional[str] = None
    role: Optional[str] = None
    id: Optional[int] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    user_role: str

class UserSignup(BaseModel):
    username: str
    email: str
    phone_number: str
    role: str
    password: str
    full_name: Optional[str] = None
    dob: Optional[str] = None
    suggested_id: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class LocationUpdate(BaseModel):
    """Schema for tourist real-time location updates with custom validation messages."""
    current_latitude: float = Field(..., description="Current latitude of the tourist")
    current_longitude: float = Field(..., description="Current longitude of the tourist")
    heart_rate: Optional[int] = Field(None, description="Current heart rate")
    spo2: Optional[int] = Field(None, description="Current SpO2 level")

    @field_validator('current_latitude')
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError('Invalid Latitude: Coordinates must be within the range of -90.0 to 90.0 degrees.')
        return v

    @field_validator('current_longitude')
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError('Invalid Longitude: Coordinates must be within the range of -180.0 to 180.0 degrees.')
        return v

    @field_validator('heart_rate')
    @classmethod
    def validate_heart_rate(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not 0 <= v <= 300:
            raise ValueError('Invalid Heart Rate: Value must be between 0 and 300 BPM.')
        return v

    @field_validator('spo2')
    @classmethod
    def validate_spo2(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not 0 <= v <= 100:
            raise ValueError('Invalid SpO2: Oxygen saturation must be between 0 and 100%.')
        return v

class IoTDataPayload(BaseModel):
    """Schema for IoT device telemetry data with health metrics validation."""
    digital_id: str
    current_latitude: float
    current_longitude: float
    heart_rate: int
    spo2: int
    sos_pressed: bool = False

    @field_validator('heart_rate')
    @classmethod
    def validate_heart_rate(cls, v: int) -> int:
        if not 0 <= v <= 300:
            raise ValueError('Invalid Heart Rate: Value must be between 0 and 300 BPM.')
        return v

    @field_validator('spo2')
    @classmethod
    def validate_spo2(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError('Invalid SpO2: Oxygen saturation must be between 0 and 100%.')
        return v

class SOSRequest(BaseModel):
    """Schema for manual SOS triggers."""
    message: Optional[str] = None
    current_latitude: Optional[float] = None
    current_longitude: Optional[float] = None

class ChatMessageRequest(BaseModel):
    """Schema for sending chat messages via REST or WebSocket."""
    recipient_id: Optional[int] = None
    message: str = Field(..., min_length=1)

class RejectionRequest(BaseModel):
    """Schema used by Verifiers to provide a reason for KYC rejection."""
    reason: str

class UserResponse(BaseModel):
    """Public-facing user profile schema."""
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_verified: bool
    digital_tourist_id: Optional[str] = None
    trip_start: Optional[str] = None
    trip_end: Optional[str] = None
    itinerary: Any
    dob: Optional[str] = None
    nationality: Optional[str] = None
    identity_type: Optional[str] = None
    identity_number: Optional[str] = None
    emergency_contact: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[str] = None

    class Config:
        from_attributes = True

class ProfileUpdateResponse(BaseModel):
    message: str
    user: UserResponse

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)