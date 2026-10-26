import smtplib
import os
from email.message import EmailMessage
from typing import Optional
from datetime import datetime

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "whitehatplayer2.0@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "kmax rvle fdwy ybeh")
AFRICA_IT_SUPPORT = "Ridkidfrosh@gmail.com"

def _send_email(subject: str, html_body: str, to_addrs: list, cc_addrs: Optional[list] = None):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = ", ".join(to_addrs)
    
    if cc_addrs:
        msg['Cc'] = ", ".join(cc_addrs)

    # Set the email content to render as HTML
    msg.set_content(html_body, subtype='html')

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            print(f"Successfully sent email: {subject}")
    except Exception as e:
        print(f"Failed to send email: {e}")

def send_initial_email(ticket):
    ticket_ref = ticket.olam_ticket_id if ticket.olam_ticket_id else f"Local ID {ticket.id}"
    subject = f"Incident: {ticket_ref} - {ticket.issue_category}"
    
    # HTML template matching Olam Agri's ServiceNow dark theme ingestion email
    html_body = f"""
    <div style="font-family: Arial, sans-serif; background-color: #333333; padding: 20px; border-radius: 8px; max-width: 600px; color: #ffffff;">
        <h2 style="color: #f26522; border-bottom: 1px solid #555; padding-bottom: 10px;">Olam Agri</h2>
        <div style="background-color: #1e1e1e; padding: 20px; border-radius: 8px;">
            <h3 style="text-align: center; border-bottom: 1px solid #555; padding-bottom: 10px; margin-top: 0;">We received your incident</h3>
            <p>Hi <strong>{ticket.plaintiff_name}</strong>,</p>
            <p>We would like to inform you that a new incident has been created on your behalf.</p>
            <p><strong>Incident:</strong> {ticket_ref}</p>
            <p><strong>Short Description:</strong> {ticket.issue_category} - {ticket.symptoms_description[:50]}...</p>
            <p>Our support team is currently reviewing your request and will work towards a timely resolution. You can track the progress of this incident via the Service Portal.</p>
            <p>If you believe any details need correction or if you have further input, feel free to reply to this email.</p>
            <p>Thank you for bringing this to our attention.</p>
            <div style="text-align: center; margin: 20px 0;">
                <a href="#" style="background-color: #a81c00; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold; width: 80%;">{ticket_ref}</a>
            </div>
            <p><strong>Thank You,<br>Olam Agri IT Service Desk</strong></p>
        </div>
    </div>
    """
    
    _send_email(
        subject=subject,
        html_body=html_body,
        to_addrs=[AFRICA_IT_SUPPORT],
        cc_addrs=[ticket.assigned_tech_email]
    )

def send_resolution_email(ticket):
    ticket_ref = ticket.olam_ticket_id if ticket.olam_ticket_id else f"Local ID {ticket.id}"
    subject = f"Resolved: {ticket_ref} - {ticket.issue_category}"
    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # HTML template matching Olam Agri's ServiceNow dark theme resolution email
    html_body = f"""
    <div style="font-family: Arial, sans-serif; background-color: #333333; padding: 20px; border-radius: 8px; max-width: 600px; color: #ffffff;">
        <h2 style="color: #f26522; border-bottom: 1px solid #555; padding-bottom: 10px;">Olam Agri</h2>
        <div style="background-color: #1e1e1e; padding: 20px; border-radius: 8px;">
            <p><strong>Hi Team,</strong></p>
            <p>The Incident ({ticket_ref} - {ticket.issue_category}) has been resolved and is now <strong>Closed</strong>.</p>
            
            <h4 style="border-bottom: 1px solid #555; padding-bottom: 5px;">Recent Comments</h4>
            <div style="font-size: 0.9em; margin-bottom: 20px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <strong>{current_time} - System</strong>
                    <span style="color: #aaaaaa; font-size: 0.8em;">Additional comments</span>
                </div>
                <p style="margin: 0;">Resolution Notes:</p>
                <p style="margin: 5px 0 0 0;">Resolved</p>
            </div>
            
            <p>If the issue reoccurs or you feel it has not been fully resolved, you may reply to this email or contact the support team for further assistance.</p>
            <p>We appreciate your collaboration throughout the process.</p>
            
            <p style="margin-bottom: 5px;">Click here to view incident.</p>
            <div style="text-align: center; margin-bottom: 20px;">
                <a href="#" style="background-color: #a81c00; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold; width: 80%;">{ticket_ref}</a>
            </div>
            
            <p style="margin-bottom: 5px;">Help us to serve you better by providing your feedback by click this button.</p>
            <div style="text-align: center; margin-bottom: 20px;">
                <a href="#" style="background-color: #555555; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold; width: 80%;">Give Feedback</a>
            </div>
            
            <p><strong>Thank You,<br>Olam Agri IT Service Desk</strong></p>
        </div>
    </div>
    """
    
    _send_email(
        subject=subject,
        html_body=html_body,
        to_addrs=[AFRICA_IT_SUPPORT],
        cc_addrs=[ticket.assigned_tech_email, ticket.plaintiff_email]
    )
