import os
import re
import json
import time
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

USCIS_BASE = "https://egov.uscis.gov"
USCIS_STATUS_URL = f"{USCIS_BASE}/casestatus/mycasestatus.do"


def build_session():
    """Build a requests session that mimics a real browser."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    })
    return session


def get_case_status_scrape(case_number):
    """Fetch USCIS case status by mimicking a real browser session."""
    session = build_session()
    try:
        # Step 1: GET the page first to get cookies & hidden form fields
        print("Step 1: Loading USCIS homepage to get session cookies...")
        get_resp = session.get(USCIS_STATUS_URL, timeout=30)
        print(f"  GET status: {get_resp.status_code}")
        get_resp.raise_for_status()
        time.sleep(2)  # mimic human delay

        # Parse hidden fields from form
        soup = BeautifulSoup(get_resp.text, "html.parser")
        form_data = {}
        for inp in soup.find_all("input", {"type": "hidden"}):
            if inp.get("name"):
                form_data[inp["name"]] = inp.get("value", "")

        # Add the case number and submit button
        form_data["appReceiptNum"] = case_number
        form_data["caseStatusSearchBtn"] = "CHECK STATUS"
        print(f"  Form data keys: {list(form_data.keys())}")

        # Step 2: POST the form
        print("Step 2: Submitting case status form...")
        post_headers = {
            "Referer": USCIS_STATUS_URL,
            "Origin": USCIS_BASE,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        session.headers.update(post_headers)
        post_resp = session.post(USCIS_STATUS_URL, data=form_data, timeout=30)
        print(f"  POST status: {post_resp.status_code}")
        post_resp.raise_for_status()

        return parse_status_html(post_resp.text, case_number)

    except Exception as e:
        print(f"Scrape attempt failed: {e}")
        return None


def parse_status_html(html, case_number):
    """Parse status title and description from USCIS HTML response."""
    soup = BeautifulSoup(html, "html.parser")

    status_title = ""
    status_desc = ""

    # Method 1: look for the known div structure
    status_div = soup.find("div", class_=re.compile(r"rows.*text-center|text-center.*rows", re.I))
    if status_div:
        h1 = status_div.find("h1")
        p = status_div.find("p")
        if h1:
            status_title = h1.get_text(strip=True)
        if p:
            status_desc = p.get_text(strip=True)

    # Method 2: scan all h1 tags
    if not status_title:
        for h1 in soup.find_all("h1"):
            text = h1.get_text(strip=True)
            if text and "uscis" not in text.lower() and len(text) > 3:
                status_title = text
                break

    # Method 3: look for 'current status' label
    if not status_title:
        for tag in soup.find_all(["h2", "h3", "p", "div"]):
            txt = tag.get_text(strip=True)
            if "case was" in txt.lower() or "your case" in txt.lower():
                status_title = txt[:120]
                break

    # Description fallback
    if not status_desc:
        for p in soup.find_all("p"):
            txt = p.get_text(strip=True)
            if len(txt) > 30:
                status_desc = txt[:500]
                break

    print(f"  Parsed title: {status_title!r}")
    print(f"  Parsed desc:  {status_desc[:100]!r}")

    if not status_title:
        # save raw html snippet for debugging
        print(f"  Raw HTML snippet: {html[:800]}")
        return None

    return {
        "case_number": case_number,
        "status_title": status_title,
        "status_description": status_desc or "See USCIS website for details.",
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


def load_last_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    return None


def save_status(status):
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


def send_email(subject, body):
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("Email credentials missing. Skipping.")
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
        print(f"Email sent to {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


def build_email_body(current, previous=None):
    change_banner = ""
    if previous and previous.get("status_title") != current["status_title"]:
        change_banner = f"""
        <div style="background:#fff3cd;border-left:5px solid #ffc107;padding:14px 18px;margin-bottom:20px;border-radius:4px;">
            <strong style="font-size:16px;">&#x26A0; Status Changed!</strong><br><br>
            <span style="color:#555;">Previous:</span> <strong>{previous['status_title']}</strong><br>
            <span style="color:#28a745;">New:</span> <strong style="color:#1a73e8;">{current['status_title']}</strong>
        </div>"""

    status_color = "#d32f2f" if "unable" in current["status_title"].lower() else "#1a73e8"

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:640px;margin:auto;padding:20px;color:#333;">
    <div style="background:#1a73e8;padding:20px 24px;border-radius:8px 8px 0 0;">
        <h2 style="color:#fff;margin:0;">&#x1F4CB; USCIS Case Status Update</h2>
    </div>
    <div style="border:1px solid #ddd;border-top:none;padding:24px;border-radius:0 0 8px 8px;background:#fff;">
        {change_banner}
        <table style="width:100%;border-collapse:collapse;font-size:15px;">
            <tr style="background:#f1f3f4;"><td style="padding:10px 14px;font-weight:bold;width:36%;">Case Number</td>
                <td style="padding:10px 14px;">{current['case_number']}</td></tr>
            <tr><td style="padding:10px 14px;font-weight:bold;">Current Status</td>
                <td style="padding:10px 14px;font-weight:bold;color:{status_color};">{current['status_title']}</td></tr>
            <tr style="background:#f1f3f4;"><td style="padding:10px 14px;font-weight:bold;">Description</td>
                <td style="padding:10px 14px;">{current['status_description']}</td></tr>
            <tr><td style="padding:10px 14px;font-weight:bold;">Checked At (UTC)</td>
                <td style="padding:10px 14px;">{current['checked_at']}</td></tr>
        </table>
        <p style="margin-top:22px;">
            <a href="https://egov.uscis.gov/casestatus/mycasestatus.do"
               style="background:#1a73e8;color:#fff;padding:10px 22px;border-radius:4px;text-decoration:none;font-weight:bold;">&#x1F517; Check on USCIS Website</a>
        </p>
        <p style="font-size:12px;color:#888;margin-top:16px;">Automated check · Runs every 5 hours via GitHub Actions</p>
    </div>
</body></html>"""


def main():
    print(f"[{datetime.utcnow().isoformat()}] Checking USCIS case: {CASE_NUMBER}")
    current = get_case_status_scrape(CASE_NUMBER)

    if current is None:
        print("Could not parse status. Sending error notification email.")
        current = {
            "case_number": CASE_NUMBER,
            "status_title": "Check Manually - USCIS blocked automated access",
            "status_description": (
                f"The USCIS website blocked this automated check. "
                f"Please visit https://egov.uscis.gov/casestatus/mycasestatus.do "
                f"and enter case number {CASE_NUMBER} to check manually."
            ),
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }

    print(f"Final status: {current['status_title']}")
    last = load_last_status()
    save_status(current)

    if last is None:
        subject = f"USCIS Case {CASE_NUMBER} - Initial Status Check"
    elif last.get("status_title") != current["status_title"]:
        subject = f"\u26a0\ufe0f USCIS STATUS CHANGED - {CASE_NUMBER}: {current['status_title']}"
    else:
        subject = f"USCIS {CASE_NUMBER} - Periodic Check ({current['status_title'][:50]})"

    send_email(subject, build_email_body(current, last))


if __name__ == "__main__":
    main()
