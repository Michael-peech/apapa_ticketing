import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import models

# --- SMTP CONFIGURATION ---
SMTP_SERVER = "smtp.gmail.com" 
SMTP_PORT = 587
SENDER_EMAIL = "whitehatplayer2.0@gmail.com"
SENDER_PASSWORD = "kmax rvle fdwy ybeh"

def _send_email(to_email: str, subject: str, body: str):
    """Internal helper function to execute the SMTP sending."""
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")

def send_initial_email(ticket: models.Ticket, tech_emails: list):
    """Loops through the list of technicians in the pool and sends the alert to each."""
    subject = f"New IT Ticket: {ticket.issue_category} at {ticket.plant_location}"
    body = f"""
    A new ticket has been raised and is waiting in the {ticket.plant_location} Team Pool.

    ID: {ticket.olam_ticket_id}
    User: {ticket.plaintiff_name} ({ticket.plaintiff_department})
    Issue: {ticket.issue_category}
    Description: {ticket.symptoms_description}
    
    Please log into the Service Desk to claim this ticket.
    """
    
    for email in tech_emails:
        _send_email(email, subject, body)

def send_resolution_email(ticket: models.Ticket):
    """Sends the RCA and fix directly to the user who raised the ticket."""
    subject = f"Resolved IT Ticket #{ticket.olam_ticket_id}"
    body = f"""
    Your IT ticket has been resolved by {ticket.assigned_tech_email}.

    Root Cause: {ticket.root_cause}
    Resolution Steps: {ticket.resolution_steps}
    """
    _send_email(ticket.plaintiff_email, subject, body)
