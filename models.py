from sqlalchemy import Column, Integer, String, Text, DateTime, Enum
from sqlalchemy.orm import declarative_base
from datetime import datetime
import enum

Base = declarative_base()

# --- EXISTING TICKET MODELS ---
class TicketStatus(enum.Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"

class Ticket(Base):
    __tablename__ = "tickets"

    # Core Identity
    id = Column(Integer, primary_key=True, index=True)
    olam_ticket_id = Column(String, index=True, nullable=True) # e.g., INC0131583

    # Ingestion (User Portal)
    plaintiff_name = Column(String, nullable=False)
    plaintiff_email = Column(String, nullable=False)
    plaintiff_department = Column(String, default="General")
    plant_location = Column(String, default="Apapa")
    issue_category = Column(String, nullable=False)
    symptoms_description = Column(Text, nullable=False)

    # Routing & State (Technician View)
    assigned_tech_email = Column(String, nullable=False)
    status = Column(Enum(TicketStatus), default=TicketStatus.OPEN)

    # Resolution Gate (Enforced Logging)
    root_cause = Column(Text, nullable=True)
    resolution_steps = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


# --- NEW USER IDENTITY MODELS ---
class UserRole(str, enum.Enum):
    USER = "user"
    TECH = "tech"
    ADMIN = "admin"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.USER)
    department = Column(String, nullable=True)
    base_plant = Column(String, default="Apapa")
