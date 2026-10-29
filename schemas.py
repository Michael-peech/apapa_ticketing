from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime
from enum import Enum

class TicketStatus(str, Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"

# 1. Base Model (Shared properties)
class TicketBase(BaseModel):
    plaintiff_name: str = Field(..., min_length=2)
    plaintiff_email: EmailStr
    plaintiff_department: str = Field(default="General")
    plant_location: str = Field(default="Apapa")
    issue_category: str = Field(..., min_length=2)
    symptoms_description: str = Field(..., min_length=10)

# 2. Ingestion Model (What the user submits in the portal)
class TicketCreate(TicketBase):
    # No RCA or resolution fields here, as the user doesn't know them yet.
    pass

# 3. The Resolution Gate (What the technician submits to close the ticket)
class TicketResolve(BaseModel):
    # Enforcing strict string lengths prevents technicians from just typing "fixed" or "N/A"
    root_cause: str = Field(..., min_length=20, description="Detailed explanation of what failed")
    resolution_steps: str = Field(..., min_length=30, description="Step-by-step actions taken to fix it")
    status: TicketStatus = TicketStatus.RESOLVED

# 4. Response Model (What the API sends back to the frontend/dashboard)
class TicketOut(TicketBase):
    id: int
    olam_ticket_id: Optional[str] = None
    assigned_tech_email: EmailStr
    status: TicketStatus
    root_cause: Optional[str] = None
    resolution_steps: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# --- USER SCHEMAS ---
class UserCreate(BaseModel):
    email: str
    password: str
    role: str = "user"
    base_plant: str = "Apapa"
    department: str = "General"

class UserOut(BaseModel):
    id: int
    email: str
    role: str

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
