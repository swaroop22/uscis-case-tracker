import os
import json
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# Configuration
CASE_NUMBER = "IOE0936799005"
EMAIL_TO = "swrp.vicky@gmail.com"
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
STATUS_FILE = "last_status.json"

USCIS_URL = "https://egov.uscis.gov/casestatus/mycasestatus.do"


def get_case_status(case_number):
    """Fetch case status from USCIS website."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    payload = {"appReceiptNum": case_number, "caseStatusSearchBtn": "CHECK STATUS"}
    try:
        response = requests.post(USCIS_URL, data=payload, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract status title
        status_title = ""
        title_tag = soup.find("h1")
        if title_tag:
            status_title = title_tag.get_text(strip=True)

        # Extract status description
        status_desc = ""
        desc_tag = soup.find("p")
        if desc_tag:
            status_desc = desc_tag.get_text(strip=True)

        # Fallback: look for the status div
        if not status_title:
            status_div = soup.find("div", {"class": "rows text-center"})
            if status_div:
                h1 = status_div.find("h1")
                p = status_div.find("p")
                if h1:
                    status_title = h1.get_text(strip=True)
                if p:
                    status_desc = p.get_text(strip=True)

        return {
            "case_number": case_number,
            "status_title": status_title or "Unknown",
            "status_description": status_desc or "No description available",
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        print(f"Error fetching status: {e}")
        return None


def load_last_status():
    """Load the previously saved status."""
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    return None


def save_status(status):
    """Save the current status to file."""
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


def send_email(subject, body, is_html=False):
    """Send an email notification."""
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("Email credentials not set. Skipping email.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        part = MIMEText(body, "html" if is_html else "plain")
        msg.attach(part)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"Email sent to {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def build_email_body(current, previous=None):
    """Build a rich HTML email body."""
    change_section = ""
    if previous and previous["status_title"] != current["status_title"]:
        change_section = f"""
        <div style="background:#fff3cd;border:1px solid #ffc107;padding:12px;border-radius:6px;margin-bottom:16px;">
            <strong>Status Changed!</strong><br>
            <span style="color:#6c757d;">Previous:</span> {previous['status_title']}<br>
            <span style="color:#28a745;">Current:</span> {current['status_title']}
        </div>
        """
    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px;">
        <h2 style="color:#1a73e8;">USCIS Case Status Update</h2>
        {change_section}
        <table style="width:100%;border-collapse:collapse;">
            <tr><td style="padding:8px;font-weight:bold;width:40%;">Case Number:</td>
                <td style="padding:8px;">{current['case_number']}</td></tr>
            <tr style="background:#f8f9fa;"><td style="padding:8px;font-weight:bold;">Current Status:</td>
                <td style="padding:8px;color:#1a73e8;">{current['status_title']}</td></tr>
            <tr><td style="padding:8px;font-weight:bold;">Description:</td>
                <td style="padding:8px;">{current['status_description']}</td></tr>
            <tr style="background:#f8f9fa;"><td style="padding:8px;font-weight:bold;">Checked At:</td>
                <td style="padding:8px;">{current['checked_at']}</td></tr>
        </table>
        <p style="margin-top:20px;font-size:12px;color:#6c757d;">
            This is an automated notification from your USCIS Case Tracker.<br>
            <a href="https://egov.uscis.gov/casestatus/mycasestatus.do">Check manually on USCIS website</a>
        </p>
    </body></html>
    """


def main():
    print(f"[{datetime.utcnow().isoformat()}] Checking USCIS case status for {CASE_NUMBER}...")
    current_status = get_case_status(CASE_NUMBER)
    if not current_status:
        print("Failed to fetch status. Exiting.")
        return

    print(f"Status: {current_status['status_title']}")
    print(f"Description: {current_status['status_description']}")

    last_status = load_last_status()
    save_status(current_status)

    if last_status is None:
        # First run — always send email
        subject = f"USCIS Case {CASE_NUMBER} - Initial Status Check"
        body = build_email_body(current_status)
        send_email(subject, body, is_html=True)
        print("First run: status email sent.")
    elif last_status["status_title"] != current_status["status_title"]:
        # Status changed
        subject = f"USCIS Status CHANGED for {CASE_NUMBER}: {current_status['status_title']}"
        body = build_email_body(current_status, last_status)
        send_email(subject, body, is_html=True)
        print("Status changed: notification email sent.")
    else:
        # No change — still send a periodic check-in email
        subject = f"USCIS Case {CASE_NUMBER} - No Change ({current_status['status_title']})"
        body = build_email_body(current_status, last_status)
        send_email(subject, body, is_html=True)
        print("No change detected. Periodic check-in email sent.")


if __name__ == "__main__":
    main()
