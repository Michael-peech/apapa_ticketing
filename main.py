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
from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

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

# 4. Admin Portal: JSON Data for Live Dashboard
@app.get("/reports/data", response_model=List[schemas.TicketOut])
def get_admin_dashboard_data(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.ADMIN]))
):
    return db.query(models.Ticket).order_by(models.Ticket.id.desc()).all()

# 5. Admin Portal: Executive PDF Report (With Summary & Text Wrapping)
@app.get("/reports/pdf")
def spool_pdf_report(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_role([models.UserRole.ADMIN]))
):
    try:
        tickets = db.query(models.Ticket).order_by(models.Ticket.id.desc()).all()
        
        # Calculate Summary Metrics
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
        
        # Executive Summary Block
        pdf.set_font('helvetica', 'B', 11)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(0, 8, f"Operational Summary: {total_tickets} Total Incidents | {resolution_rate}% Resolution Rate", ln=1)
        pdf.ln(3)

        # Dynamic Wrapping Table
        pdf.set_font('helvetica', '', 9)
        with pdf.table(text_align="LEFT", cell_fill_color=(244, 247, 246), cell_fill_mode="ROWS") as table:
            # Header
            row = table.row()
            for header in ["ID", "Category", "Plaintiff", "Assigned Tech", "RCA & Resolution Summary", "SLA (Hrs)"]:
                row.cell(header)
            
            # Data Rows
            for t in tickets:
                row = table.row()
                # Calculate SLA
                sla = "N/A"
                if t.created_at and t.resolved_at:
                    hrs = (t.resolved_at - t.created_at).total_seconds() / 3600
                    sla = f"{hrs:.1f}h"
                
                tech = t.assigned_tech_email.split('@')[0] if t.assigned_tech_email else "Unassigned"
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

# 6. Admin Portal: Excel Data Dump (Formatted)
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
        
        # Corporate Styling for Headers
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
            
        # Auto-adjust column widths and enable text wrapping
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except: pass
            ws.column_dimensions[column].width = min(max_length + 2, 60) # Cap at 60 wide
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
