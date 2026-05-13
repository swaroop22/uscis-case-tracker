import os
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── Configuration
CASE_NUMBER    = "IOE0936799005"
EMAIL_TO       = "swrp.vicky@gmail.com"
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
STATUS_FILE    = "last_status.json"
USCIS_URL      = "https://egov.uscis.gov/casestatus/mycasestatus.do"


def get_case_status(case_number: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            java_script_enabled=True,
        )
        page = ctx.new_page()
        try:
            print(f"Navigating to {USCIS_URL} ...")
            page.goto(USCIS_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            # Debug: dump all input names on the page
            inputs = page.eval_on_selector_all("input", "els => els.map(e => e.name + '|' + e.id + '|' + e.type)")
            print(f"Inputs found: {inputs}")

            # Debug: dump page title and URL after load
            print(f"Page URL  : {page.url}")
            print(f"Page title: {page.title()}")

            # Try multiple selector strategies for the receipt number field
            receipt_selectors = [
                "input[name='appReceiptNum']",
                "input[id='appReceiptNum']",
                "input[placeholder*='receipt' i]",
                "input[placeholder*='case' i]",
                "input[placeholder*='IOE' i]",
                "#receipt-number",
                "input[type='text']",
            ]

            filled = False
            for sel in receipt_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        print(f"Found input with selector: {sel}")
                        el.click()
                        page.wait_for_timeout(300)
                        el.fill(case_number)
                        filled = True
                        break
                except Exception as e:
                    print(f"  selector {sel} failed: {e}")

            if not filled:
                body_text = page.inner_text("body")[:1500]
                print(f"Could not find input. Page body:\n{body_text}")
                return None

            # Submit the form
            submit_selectors = [
                "input[name='caseStatusSearchBtn']",
                "button[type='submit']",
                "input[type='submit']",
                "button[id*='check' i]",
                "button[id*='status' i]",
                "[class*='btn']:has-text('Check')",
            ]
            submitted = False
            for sel in submit_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        print(f"Clicking submit with selector: {sel}")
                        el.click()
                        submitted = True
                        break
                except Exception as e:
                    print(f"  submit selector {sel} failed: {e}")

            if not submitted:
                # Fallback: press Enter
                print("No submit button found, pressing Enter...")
                page.keyboard.press("Enter")

            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            print(f"Post-submit URL: {page.url}")

            # Extract status
            status_title = ""
            status_desc  = ""

            title_selectors = [
                ".rows.text-center h1",
                ".current-case-status h1",
                ".case-status h1",
                "h1.h2",
                "h1",
            ]
            for sel in title_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        t = el.inner_text().strip()
                        if t and len(t) > 3 and "uscis" not in t.lower():
                            status_title = t
                            print(f"Status title via '{sel}': {t!r}")
                            break
                except Exception:
                    pass

            desc_selectors = [
                ".rows.text-center p",
                ".current-case-status p",
                ".case-status p",
                "p",
            ]
            for sel in desc_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        t = el.inner_text().strip()
                        if len(t) > 20:
                            status_desc = t[:600]
                            break
                except Exception:
                    pass

            if not status_title:
                body = page.inner_text("body")[:2000]
                print(f"No title found. Full body text:\n{body}")
                return None

            return {
                "case_number"        : case_number,
                "status_title"       : status_title,
                "status_description" : status_desc or "See USCIS website for full details.",
                "checked_at"         : datetime.utcnow().isoformat() + "Z",
            }
        except PlaywrightTimeout as e:
            print(f"Playwright timeout: {e}")
            try:
                body = page.inner_text("body")[:1500]
                print(f"Page at timeout:\n{body}")
            except Exception:
                pass
            return None
        except Exception as e:
            print(f"Error: {e}")
            return None
        finally:
            browser.close()


def load_last_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            return json.load(f)
    return None


def save_status(status):
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


def send_email(subject, body):
    if not EMAIL_FROM or not EMAIL_PASSWORD:
        print("Email credentials missing.")
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


def build_email_body(current, previous=None):
    change_banner = ""
    if previous and previous.get("status_title") != current["status_title"]:
        change_banner = f"""
        <div style="background:#fff3cd;border-left:5px solid #ffc107;
                    padding:14px 18px;margin-bottom:20px;border-radius:4px;">
          <strong>&#x26A0; Status Changed!</strong><br><br>
          Previous: <strong>{previous['status_title']}</strong><br>
          New: <strong style="color:#1a73e8;">{current['status_title']}</strong>
        </div>"""

    is_err  = any(w in current["status_title"].lower() for w in ("failed","blocked","manually"))
    color   = "#d32f2f" if is_err else "#1a73e8"

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
        <td style="padding:10px 14px;font-weight:bold;color:{color};">{current['status_title']}</td></tr>
      <tr style="background:#f1f3f4;"><td style="padding:10px 14px;font-weight:bold;">Description</td>
        <td style="padding:10px 14px;">{current['status_description']}</td></tr>
      <tr><td style="padding:10px 14px;font-weight:bold;">Checked At (UTC)</td>
        <td style="padding:10px 14px;">{current['checked_at']}</td></tr>
    </table>
    <p style="margin-top:22px;">
      <a href="{USCIS_URL}" style="background:#1a73e8;color:#fff;padding:10px 22px;
         border-radius:4px;text-decoration:none;font-weight:bold;">&#x1F517; Check on USCIS Website</a>
    </p>
    <p style="font-size:12px;color:#888;margin-top:16px;">Automated check &middot; Runs every 5 hours via GitHub Actions</p>
  </div>
</body></html>"""


def main():
    print(f"[{datetime.utcnow().isoformat()}Z] Checking USCIS case: {CASE_NUMBER}")
    current = get_case_status(CASE_NUMBER)

    if current is None:
        current = {
            "case_number"       : CASE_NUMBER,
            "status_title"      : "Check Manually - automated fetch failed",
            "status_description": f"Could not retrieve status automatically. Please visit {USCIS_URL} and enter {CASE_NUMBER}.",
            "checked_at"        : datetime.utcnow().isoformat() + "Z",
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
