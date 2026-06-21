from enum import Enum
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict


class Operation(str, Enum):
    add = "add"
    subtract = "subtract"
    multiply = "multiply"
    divide = "divide"
    percentage = "percentage"


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    num1: float = Field(..., description="First number")
    num2: float = Field(..., description="Second number")
    operation: Operation = Field(..., description="Operation to perform")


class CalculationResponse(BaseModel):
    num1: float
    num2: float
    operation: str
    result: float


app = FastAPI(
    title="Calculator API",
    version="1.0.0",
    description="Simple production-ready calculator API",
)

# Set your frontend URL in env, for example:
# CORS_ORIGINS=https://your-frontend.com,https://www.your-frontend.com
cors_origins_env = os.getenv("CORS_ORIGINS", "")
allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

# In production, avoid "*" with credentials.
# If no env is set, this falls back to localhost only.
if not allowed_origins:
    allowed_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/", response_model=CalculationResponse)
def calculator(data: CalculationRequest):
    if data.operation == Operation.add:
        result = data.num1 + data.num2

    elif data.operation == Operation.subtract:
        result = data.num1 - data.num2

    elif data.operation == Operation.multiply:
        result = data.num1 * data.num2

    elif data.operation == Operation.divide:
        if data.num2 == 0:
            raise HTTPException(
                status_code=400,
                detail="Division by zero is not allowed.",
            )
        result = data.num1 / data.num2

    elif data.operation == Operation.percentage:
        result = (data.num1 * data.num2) / 100

    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid operation. Use add, subtract, multiply, divide, or percentage.",
        )

    return CalculationResponse(
        num1=data.num1,
        num2=data.num2,
        operation=data.operation.value,
        result=result,
    )