import csv
import io
from fastapi import Response
from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import List

import models, schemas, email_service
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Apapa IT Ticket MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for MVP testing
    allow_credentials=True,
    allow_methods=["*"],  # Allows POST, GET, PATCH, etc.
    allow_headers=["*"],
)

# --- SECURITY CONFIGURATION ---
SECRET_KEY = "super_secret_olam_key_change_in_production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, 
        detail="Could not validate credentials", 
        headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

def require_role(allowed_roles: list[str]):
    def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Operation not permitted. Insufficient clearance.")
        return current_user
    return role_checker

# --- AUTH ROUTES ---
@app.post("/token", response_model=schemas.Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

# --- APPLICATION ROUTES ---

# 1. User Portal: Ticket Ingestion (Requires Base Login)
@app.post("/tickets/", response_model=schemas.TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(
    ticket: schemas.TicketCreate, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    assigned_tech = "makabogu55@gmail.com" 
    
    db_ticket = models.Ticket(
        **ticket.model_dump(),
        assigned_tech_email=assigned_tech
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    
    background_tasks.add_task(email_service.send_initial_email, db_ticket)
    
    return db_ticket

# 2. Technician View: Active Queue (Locked to Techs & Admins)
@app.get("/tickets/active", response_model=List[schemas.TicketOut])
def get_active_tickets(
    tech_email: str, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.TECH, models.UserRole.ADMIN]))
):
    tickets = db.query(models.Ticket).filter(
        models.Ticket.assigned_tech_email == tech_email,
        models.Ticket.status != models.TicketStatus.RESOLVED
    ).all()
    return tickets

# 3. Resolution Gate: Enforced Logging (Locked to Techs & Admins)
@app.patch("/tickets/{ticket_id}/resolve", response_model=schemas.TicketOut)
def resolve_ticket(
    ticket_id: int, 
    resolution_data: schemas.TicketResolve, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.TECH, models.UserRole.ADMIN]))
):
    db_ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if db_ticket.status == models.TicketStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Ticket is already resolved")

    db_ticket.root_cause = resolution_data.root_cause
    db_ticket.resolution_steps = resolution_data.resolution_steps
    db_ticket.status = models.TicketStatus.RESOLVED
    db_ticket.resolved_at = datetime.utcnow()

    db.commit()
    db.refresh(db_ticket)
    
    background_tasks.add_task(email_service.send_resolution_email, db_ticket)

    return db_ticket

# 4. Admin Portal: CSV Report Spooling (Locked to Admins Only)
@app.get("/reports/csv")
def spool_csv_report(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.ADMIN]))
):
    try:
        # Retrieve all tickets from the database
        tickets = db.query(models.Ticket).all()

        # Create an in-memory string buffer for the CSV data
        output = io.StringIO()
        writer = csv.writer(output)

        # Write the header row
        writer.writerow([
            "Ticket ID", "Olam Ref ID", "Plaintiff Name", "Plaintiff Email",
            "Issue Category", "Symptoms/Description", "Assigned Tech", 
            "Status", "Root Cause", "Resolution Steps", "Created At", "Resolved At"
        ])

        # Write the data rows with fault-tolerant type casting
        for t in tickets:
            # Safely parse Enums and Datetimes to strings to prevent SQLite type crashes
            status_str = t.status.value if hasattr(t.status, "value") else str(t.status)
            created_str = t.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(t.created_at, "strftime") else str(t.created_at)
            resolved_str = t.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(t.resolved_at, "strftime") else str(t.resolved_at)

            writer.writerow([
                t.id,
                t.olam_ticket_id or "N/A",
                t.plaintiff_name,
                t.plaintiff_email,
                t.issue_category,
                t.symptoms_description,
                t.assigned_tech_email,
                status_str,
                t.root_cause or "N/A",
                t.resolution_steps or "N/A",
                created_str,
                resolved_str
            ])

        # Construct the file download response
        response = Response(content=output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=Apapa_IT_Report.csv"
        response.headers["Content-Type"] = "text/csv"
        
        return response
        
    except Exception as e:
        print(f"CRITICAL CSV ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to compile CSV report.")
