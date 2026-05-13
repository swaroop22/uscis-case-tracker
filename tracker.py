import os
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Configuration ─────────────────────────────────────────────────────────────
CASE_NUMBER   = "IOE0936799005"
EMAIL_TO      = "swrp.vicky@gmail.com"
EMAIL_FROM    = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
STATUS_FILE   = "last_status.json"
USCIS_URL     = "https://egov.uscis.gov/casestatus/mycasestatus.do"


# ── USCIS Fetcher ─────────────────────────────────────────────────────────────
def get_case_status(case_number: str) -> dict | None:
    """Use Playwright headless Chromium to load the USCIS page like a real browser."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()

        try:
            print("Loading USCIS case status page...")
            page.goto(USCIS_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2000)  # let JS settle

            # Fill in case number
            print(f"Filling case number: {case_number}")
            page.fill('input[name="appReceiptNum"]', case_number)
            page.wait_for_timeout(500)

            # Click submit button
            print("Submitting form...")
            page.click('input[name="caseStatusSearchBtn"], button[id*="case"], input[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_timeout(2000)

            # Extract status title
            status_title = ""
            status_desc  = ""

            # Try the main status heading
            for selector in [
                ".rows.text-center h1",
                ".current-case-status h1",
                "#formErrorMessages + div h1",
                "h1",
            ]:
                try:
                    el = page.query_selector(selector)
                    if el:
                        text = el.inner_text().strip()
                        if text and "uscis" not in text.lower() and len(text) > 3:
                            status_title = text
                            break
                except Exception:
                    pass

            # Try description paragraph
            for selector in [
                ".rows.text-center p",
                ".current-case-status p",
                "p",
            ]:
                try:
                    el = page.query_selector(selector)
                    if el:
                        text = el.inner_text().strip()
                        if len(text) > 20:
                            status_desc = text[:600]
                            break
                except Exception:
                    pass

            print(f"Title found  : {status_title!r}")
            print(f"Desc  found  : {status_desc[:80]!r}")

            if not status_title:
                # Dump page text for debugging
                print("[DEBUG] Page text:", page.inner_text("body")[:800])
                return None

            return {
                "case_number"       : case_number,
                "status_title"      : status_title,
                "status_description": status_desc or "See USCIS website for details.",
                "checked_at"        : datetime.utcnow().isoformat() + "Z",
            }

        except PlaywrightTimeout as e:
            print(f"Timeout error: {e}")
            return None
        except Exception as e:
            print(f"Error during scraping: {e}")
            return None
        finally:
            browser.close()


# ── Persistence ───────────────────────────────────────────────────────────────
def load_last_status() -> dict | None:
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            return json.load(f)
    return None


def save_status(status: dict):
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(subject: str, body: str) -> bool:
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("Email credentials missing - skipping send.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"Email sent to {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


def build_email_body(current: dict, previous: dict | None = None) -> str:
    change_banner = ""
    if previous and previous.get("status_title") != current["status_title"]:
        change_banner = f"""
        <div style="background:#fff3cd;border-left:5px solid #ffc107;
                    padding:14px 18px;margin-bottom:20px;border-radius:4px;">
          <strong style="font-size:16px;">&#x26A0; Status Changed!</strong><br><br>
          <span style="color:#555;">Previous:</span>
          <strong>{previous['status_title']}</strong><br>
          <span style="color:#28a745;">New:</span>
          <strong style="color:#1a73e8;">{current['status_title']}</strong>
        </div>"""

    is_error = "blocked" in current["status_title"].lower() or "manually" in current["status_title"].lower()
    status_color = "#d32f2f" if is_error else "#1a73e8"

    return f"""<html><body style="font-family:Arial,sans-serif;max-width:640px;
                               margin:auto;padding:20px;color:#333;">
  <div style="background:#1a73e8;padding:20px 24px;border-radius:8px 8px 0 0;">
    <h2 style="color:#fff;margin:0;">&#x1F4CB; USCIS Case Status Update</h2>
  </div>
  <div style="border:1px solid #ddd;border-top:none;padding:24px;
              border-radius:0 0 8px 8px;background:#fff;">
    {change_banner}
    <table style="width:100%;border-collapse:collapse;font-size:15px;">
      <tr style="background:#f1f3f4;">
        <td style="padding:10px 14px;font-weight:bold;width:36%;">Case Number</td>
        <td style="padding:10px 14px;">{current['case_number']}</td>
      </tr>
      <tr>
        <td style="padding:10px 14px;font-weight:bold;">Current Status</td>
        <td style="padding:10px 14px;font-weight:bold;color:{status_color};">
          {current['status_title']}</td>
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
      <a href="{USCIS_URL}"
         style="background:#1a73e8;color:#fff;padding:10px 22px;
                border-radius:4px;text-decoration:none;font-weight:bold;">
        &#x1F517; Check on USCIS Website
      </a>
    </p>
    <p style="font-size:12px;color:#888;margin-top:16px;">
      Automated check &middot; Runs every 5 hours via GitHub Actions
    </p>
  </div>
</body></html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.utcnow().isoformat()}] Checking USCIS case: {CASE_NUMBER}")
    current = get_case_status(CASE_NUMBER)

    if current is None:
        print("Status fetch failed - sending fallback email.")
        current = {
            "case_number"       : CASE_NUMBER,
            "status_title"      : "Check Manually - automated fetch failed",
            "status_description": (
                f"The automated check could not retrieve the status. "
                f"Please visit {USCIS_URL} and enter {CASE_NUMBER}."
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
        subject = f"USCIS {CASE_NUMBER} - Check ({current['status_title'][:55]})"

    send_email(subject, build_email_body(current, last))


if __name__ == "__main__":
    main()
