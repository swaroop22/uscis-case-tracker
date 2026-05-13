import os
import json
import smtplib
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configuration
CASE_NUMBER = "IOE0936799005"
EMAIL_TO = "swrp.vicky@gmail.com"
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
STATUS_FILE = "last_status.json"

# USCIS public case status API
USCIS_API_URL = "https://egov.uscis.gov/case-status/api/getCaseStatus"


def get_case_status(case_number):
    """Fetch case status using the USCIS public API."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://egov.uscis.gov/casestatus/mycasestatus.do",
        "Origin": "https://egov.uscis.gov",
    }
    params = {"appReceiptNum": case_number}
    try:
        response = requests.get(
            USCIS_API_URL,
            params=params,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        print(f"Raw API response: {json.dumps(data, indent=2)}")

        # Parse the API response structure
        case_status = data.get("caseStatus", {})
        status_title = (
            case_status.get("formType", "")
            + " - "
            + case_status.get("subStatus", "")
        ).strip(" -")
        if not status_title:
            status_title = case_status.get("current_case_status_text_en", "Unknown")
        status_desc = case_status.get("current_case_status_desc_en", "No description available")

        return {
            "case_number": case_number,
            "status_title": status_title or "Unknown",
            "status_description": status_desc,
            "raw": case_status,
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        print(f"API request failed: {e}")
        # Fallback: try the eVerify/external tracker endpoint
        return get_case_status_fallback(case_number)


def get_case_status_fallback(case_number):
    """Fallback using alternate USCIS endpoint."""
    try:
        url = f"https://egov.uscis.gov/case-status/api/check-case/{case_number}"
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://egov.uscis.gov/",
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        print(f"Fallback API response: {json.dumps(data, indent=2)}")
        status_title = data.get("subStatus", data.get("status", "Unknown"))
        status_desc = data.get("description", "No description available")
        return {
            "case_number": case_number,
            "status_title": status_title,
            "status_description": status_desc,
            "raw": data,
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e2:
        print(f"Fallback also failed: {e2}")
        # Return a placeholder so we still send an email with error info
        return {
            "case_number": case_number,
            "status_title": "Unable to fetch - USCIS website blocked request",
            "status_description": (
                f"Both USCIS API endpoints returned errors. "
                f"Please check manually at https://egov.uscis.gov/casestatus/mycasestatus.do "
                f"using case number {case_number}. Error: {e2}"
            ),
            "raw": {},
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }


def load_last_status():
    """Load the previously saved status."""
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    return None


def save_status(status):
    """Save current status to file."""
    saveable = {k: v for k, v in status.items() if k != "raw"}
    with open(STATUS_FILE, "w") as f:
        json.dump(saveable, f, indent=2)


def send_email(subject, body):
    """Send HTML email notification."""
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("Email credentials not configured. Skipping email.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"Email sent successfully to {EMAIL_TO}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP Authentication failed: {e}")
        return False
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def build_email_body(current, previous=None):
    """Build HTML email body."""
    change_banner = ""
    if previous and previous.get("status_title") != current["status_title"]:
        change_banner = f"""
        <div style="background:#fff3cd;border-left:4px solid #ffc107;padding:14px 16px;border-radius:4px;margin-bottom:20px;">
            <strong style="font-size:16px;">&#x26A0; Status Changed!</strong><br><br>
            <span style="color:#666;">Previous:</span> <strong>{previous['status_title']}</strong><br>
            <span style="color:#28a745;">New:</span> <strong>{current['status_title']}</strong>
        </div>"""

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:620px;margin:auto;padding:24px;color:#333;">
    <div style="background:#1a73e8;padding:20px 24px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;">&#x1F4CB; USCIS Case Status Update</h2>
    </div>
    <div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
        {change_banner}
        <table style="width:100%;border-collapse:collapse;font-size:15px;">
            <tr style="background:#f1f3f4;">
                <td style="padding:10px 14px;font-weight:bold;width:38%;">Case Number</td>
                <td style="padding:10px 14px;">{current['case_number']}</td>
            </tr>
            <tr>
                <td style="padding:10px 14px;font-weight:bold;">Current Status</td>
                <td style="padding:10px 14px;color:#1a73e8;font-weight:bold;">{current['status_title']}</td>
            </tr>
            <tr style="background:#f1f3f4;">
                <td style="padding:10px 14px;font-weight:bold;">Description</td>
                <td style="padding:10px 14px;">{current['status_description']}</td>
            </tr>
            <tr>
                <td style="padding:10px 14px;font-weight:bold;">Checked At (UTC)</td>
                <td style="padding:10px 14px;">{current['checked_at']}</td>
            </tr>
        </table>
        <p style="margin-top:22px;">
            <a href="https://egov.uscis.gov/casestatus/mycasestatus.do" 
               style="background:#1a73e8;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;font-weight:bold;">
                Check on USCIS Website
            </a>
        </p>
        <p style="font-size:12px;color:#888;margin-top:20px;">This is an automated check from your GitHub USCIS tracker. Runs every 5 hours.</p>
    </div>
</body></html>"""


def main():
    print(f"[{datetime.utcnow().isoformat()}] Checking USCIS status for case {CASE_NUMBER}...")
    current = get_case_status(CASE_NUMBER)
    if not current:
        print("No status returned. Exiting.")
        return

    print(f"Status title: {current['status_title']}")
    print(f"Description:  {current['status_description']}")

    last = load_last_status()
    save_status(current)

    if last is None:
        subject = f"USCIS Case {CASE_NUMBER} - First Status Check"
        print("First run - sending initial status email.")
    elif last.get("status_title") != current["status_title"]:
        subject = f"\u26a0 USCIS STATUS CHANGED for {CASE_NUMBER}: {current['status_title']}"
        print("Status changed - sending alert email.")
    else:
        subject = f"USCIS Case {CASE_NUMBER} - Check-in ({current['status_title']})"
        print("No change - sending periodic check-in email.")

    send_email(subject, build_email_body(current, last))


if __name__ == "__main__":
    main()
