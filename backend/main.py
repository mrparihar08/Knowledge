import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base
from routers import auth, tourist, emergency, verifier, admin, profile, iot

# Initialize SQLite Database Tables
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for document viewing
os.makedirs("uploads/documents", exist_ok=True)
os.makedirs("uploads/profiles", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Include Routers
app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])
app.include_router(tourist.router, prefix="/api/v1", tags=["Tourist Actions"])
app.include_router(emergency.router, prefix="/api/v1", tags=["Emergency & SOS"])
app.include_router(verifier.router, prefix="/api/v1", tags=["KYC Verification"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin Authority"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["Profile Management"])
app.include_router(iot.router, prefix="/api/v1", tags=["IoT & Health Monitoring"])