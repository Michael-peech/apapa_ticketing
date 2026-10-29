import csv
import io
from fastapi import Response, FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import List
from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from pydantic import BaseModel

import models, schemas, email_service
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Apapa IT Ticket MVP")

@app.on_event("startup")
def create_initial_admin():
    db = next(get_db())
    admin_exists = db.query(models.User).filter(models.User.email == "admin@olamagri.com").first()
    if not admin_exists:
        admin_user = models.User(
            email="admin@olamagri.com",
            hashed_password=get_password_hash("admin123!"),
            role=models.UserRole.ADMIN,
            base_plant="Apapa",
            department="IT"
        )
        db.add(admin_user)
        db.commit()
        print("Default admin account created: admin@olamagri.com / admin123!")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
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

def require_role(allowed_roles: list):
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
        data={
            "sub": user.email, 
            "role": user.role.value if hasattr(user.role, 'value') else user.role,
            "base_plant": getattr(user, 'base_plant', 'Apapa'),
            "department": getattr(user, 'department', 'General')
        }, 
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

# --- MVP POOL & NOTIFICATION ROUTING ---
def get_pool_name(location: str) -> str:
    # Generates a database string like "POOL-APAPA" to hold the unassigned ticket
    return f"POOL-{location.upper()}"

def get_plant_tech_emails(location: str) -> list:
    # Returns the list of actual technician emails for the email_service to fan-out to
    routing_table = {
        "Apapa": ["makabogu55@gmail.com", "admin@olamagri.com"],
        "Tincan": ["tincan.it@olamagri.com"],
        "Ikorodu": ["ikorodu.it@olamagri.com"]
    }
    return routing_table.get(location, ["oluwatobiloba69@gmail.com"])


# --- APPLICATION ROUTES ---
@app.post("/tickets/", response_model=schemas.TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(
    ticket: schemas.TicketCreate, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # 1. Assign to the string database pool (e.g., POOL-APAPA)
    pool_assignment = get_pool_name(ticket.plant_location)
    
    db_ticket = models.Ticket(
        **ticket.model_dump(),
        assigned_tech_email=pool_assignment
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    
    # 2. Fan-out to the actual emails of the technicians via background task
    tech_emails = get_plant_tech_emails(ticket.plant_location)
    background_tasks.add_task(email_service.send_initial_email, db_ticket, tech_emails)
    
    return db_ticket

# Gets tickets claimed by the logged-in technician (My Workspace)
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

# Gets unassigned tickets waiting in a specific plant's pool (Team Pool)
@app.get("/tickets/pool", response_model=List[schemas.TicketOut])
def get_pool_tickets(
    plant_location: str, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.TECH, models.UserRole.ADMIN]))
):
    pool_assignment = get_pool_name(plant_location)
    tickets = db.query(models.Ticket).filter(
        models.Ticket.assigned_tech_email == pool_assignment,
        models.Ticket.status != models.TicketStatus.RESOLVED
    ).all()
    return tickets

# New endpoint to claim an unassigned ticket
@app.patch("/tickets/{ticket_id}/claim", response_model=schemas.TicketOut)
def claim_ticket(
    ticket_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.TECH, models.UserRole.ADMIN]))
):
    db_ticket = db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()
    if not db_ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    if not str(db_ticket.assigned_tech_email).startswith("POOL-"):
        raise HTTPException(status_code=400, detail="Ticket has already been claimed by someone else.")

    # Assign it to the technician who clicked claim and change status
    db_ticket.assigned_tech_email = current_user.email
    db_ticket.status = models.TicketStatus.IN_PROGRESS
    
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

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

@app.get("/reports/data", response_model=List[schemas.TicketOut])
def get_admin_dashboard_data(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.ADMIN]))
):
    return db.query(models.Ticket).order_by(models.Ticket.id.desc()).all()

@app.get("/reports/pdf")
def spool_pdf_report(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.ADMIN]))
):
    try:
        tickets = db.query(models.Ticket).order_by(models.Ticket.id.desc()).all()
        total_tickets = len(tickets)
        resolved_tickets = [t for t in tickets if (t.status.value if hasattr(t.status, "value") else str(t.status)) == "Resolved"]
        resolution_rate = round((len(resolved_tickets) / total_tickets) * 100) if total_tickets > 0 else 0

        class PDFReport(FPDF):
            def header(self):
                self.set_font('helvetica', 'B', 16)
                self.set_text_color(242, 101, 34)
                self.cell(0, 10, 'Olam Agri | Apapa IT Executive Report', border=0, ln=1, align='L')
                self.set_font('helvetica', 'I', 10)
                self.set_text_color(100, 100, 100)
                self.cell(0, 6, 'Generated by Service Desk Admin', border=0, ln=1, align='L')
                self.ln(5)

        pdf = PDFReport(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        
        pdf.set_font('helvetica', 'B', 11)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(0, 8, f"Operational Summary: {total_tickets} Total Incidents | {resolution_rate}% Resolution Rate", ln=1)
        pdf.ln(3)

        pdf.set_font('helvetica', '', 9)
        with pdf.table(text_align="LEFT", cell_fill_color=(244, 247, 246), cell_fill_mode="ROWS") as table:
            row = table.row()
            for header in ["ID", "Category", "Plaintiff", "Assigned Tech", "RCA & Resolution Summary", "SLA (Hrs)"]:
                row.cell(header)
            
            for t in tickets:
                row = table.row()
                sla = "N/A"
                if t.created_at and t.resolved_at:
                    hrs = (t.resolved_at - t.created_at).total_seconds() / 3600
                    sla = f"{hrs:.1f}h"
                
                tech = str(t.assigned_tech_email).split('@')[0] if t.assigned_tech_email else "Unassigned"
                if str(t.assigned_tech_email).startswith("POOL-"): tech = "Pool"

                rca_text = f"Cause: {t.root_cause or 'N/A'}\nFix: {t.resolution_steps or 'N/A'}"
                
                row.cell(str(t.id))
                row.cell(t.issue_category)
                row.cell(t.plaintiff_name)
                row.cell(tech)
                row.cell(rca_text)
                row.cell(sla)

        response = Response(content=bytes(pdf.output()))
        response.headers["Content-Disposition"] = "attachment; filename=Olam_IT_Executive_Report.pdf"
        response.headers["Content-Type"] = "application/pdf"
        return response
    except Exception as e:
        print(f"CRITICAL PDF ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to compile PDF report.")

@app.get("/reports/excel")
def spool_excel_report(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.ADMIN]))
):
    try:
        tickets = db.query(models.Ticket).order_by(models.Ticket.id.desc()).all()
        wb = Workbook()
        ws = wb.active
        ws.title = "Incident Report"
        
        headers = ["Ticket ID", "Category", "Plaintiff Name", "Assigned Tech", "Status", "Root Cause", "Resolution Steps", "Created At", "Resolved At", "SLA (Hours)"]
        ws.append(headers)
        
        header_fill = PatternFill(start_color="F26522", end_color="F26522", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
            
        for t in tickets:
            sla = ""
            if t.resolved_at and t.created_at:
                sla = round((t.resolved_at - t.created_at).total_seconds() / 3600, 2)
                
            ws.append([
                t.id, t.issue_category, t.plaintiff_name, t.assigned_tech_email, 
                t.status.value if hasattr(t.status, "value") else str(t.status),
                t.root_cause or "N/A", t.resolution_steps or "N/A",
                t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else "",
                t.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if t.resolved_at else "",
                sla
            ])
            
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except: pass
            ws.column_dimensions[column].width = min(max_length + 2, 60) 
            for cell in col:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                
        ws.auto_filter.ref = ws.dimensions
        
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        response = Response(content=output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=Olam_IT_Operations_Report.xlsx"
        response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return response
    except Exception as e:
        print(f"CRITICAL EXCEL ERROR: {e}")
        raise HTTPException(status_code=500, detail="Failed to compile Excel report.")


# --- NEW ENDPOINTS (My Tickets & User Creation) ---
class UserCreate(BaseModel):
    email: str 
    password: str
    role: str
    base_plant: str
    department: str

@app.get("/tickets/me", response_model=List[schemas.TicketOut])
def get_my_tickets(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return db.query(models.Ticket).filter(models.Ticket.plaintiff_email == current_user.email).order_by(models.Ticket.id.desc()).all()

@app.post("/admin/users", status_code=status.HTTP_201_CREATED)
def create_privileged_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.ADMIN]))
):
    try:
        role_enum = models.UserRole(user_data.role)
        
        new_user = models.User(
            email=user_data.email,
            hashed_password=get_password_hash(user_data.password),
            role=role_enum,
            base_plant=user_data.base_plant,
            department=user_data.department
        )
        db.add(new_user)
        db.commit()
        return {"message": f"User {user_data.email} granted access."}
    except Exception as e:
        db.rollback()
        print(f"CRITICAL USER CREATION ERROR: {e}")
        raise HTTPException(status_code=400, detail="Email already exists or invalid data.")
