"""
Email + SMS notifications for suburb subscribers.

EMAIL has two backends:
- Resend (preferred if RESEND_API_KEY is set): a simple HTTPS API call,
  no SMTP setup, no app passwords. This is what activates if you've
  provided a Resend key.
- Plain SMTP (fallback): works with any real mail account (Gmail,
  Outlook, etc) if EMAIL_USER/EMAIL_PASSWORD are set instead.
If neither is configured, send_email() logs what it would have sent.

SMS is wired up for Twilio's REST API (the most common provider), but
there's no way around this needing a paid account -- there's no free
tier for sending real text messages anywhere. Until TWILIO_ACCOUNT_SID
/ TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER are set, send_sms() just logs
what it *would* have sent, so you can build and test the rest of the
flow (subscriptions, triggers, message content) without paying for
anything yet.
"""

import logging
import smtplib
from email.mime.text import MIMEText

import requests

import config

import os
os.makedirs(config.LOG_DIR, exist_ok=True)

logger = logging.getLogger("notifications")
if not logger.handlers:
    _handler = logging.FileHandler(config.LOG_FILE)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

def _send_via_resend(to_address: str, subject: str, body: str) -> bool:
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {config.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": config.RESEND_FROM_ADDRESS,
                "to": [to_address],
                "subject": subject,
                # Resend accepts either `html` or `text` -- plain text is
                # fine here and keeps this in sync with the SMTP path.
                "text": body,
            },
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"Email sent via Resend to {to_address}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Resend send failed for {to_address}: {e}")
        return False


def _send_via_smtp(to_address: str, subject: str, body: str) -> bool:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = to_address

    try:
        with smtplib.SMTP(config.EMAIL_HOST, config.EMAIL_PORT, timeout=15) as server:
            server.starttls()
            server.login(config.EMAIL_USER, config.EMAIL_PASSWORD)
            server.sendmail(config.EMAIL_FROM, [to_address], msg.as_string())
        logger.info(f"Email sent via SMTP to {to_address}: {subject}")
        return True
    except Exception as e:
        logger.error(f"SMTP send failed for {to_address}: {e}")
        return False


def send_email(to_address: str, subject: str, body: str) -> bool:
    if config.ENABLE_RESEND:
        return _send_via_resend(to_address, subject, body)
    if config.ENABLE_EMAIL_NOTIFICATIONS:
        return _send_via_smtp(to_address, subject, body)
    logger.info(f"[email disabled] Would have sent to {to_address}: {subject}")
    return False


# --------------------------------------------------------------------------
# SMS (Twilio)
# --------------------------------------------------------------------------

def send_sms(to_number: str, body: str) -> bool:
    if not config.ENABLE_SMS_NOTIFICATIONS:
        logger.info(f"[sms disabled -- no Twilio credentials set] Would have sent to {to_number}: {body}")
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json"
    try:
        resp = requests.post(
            url,
            data={
                "From": config.TWILIO_FROM_NUMBER,
                "To": to_number,
                "Body": body,
            },
            auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"SMS sent to {to_number}")
        return True
    except Exception as e:
        logger.error(f"Failed to send SMS to {to_number}: {e}")
        return False


# --------------------------------------------------------------------------
# Message content + fan-out to subscribers
# --------------------------------------------------------------------------

def _outage_message(outage: dict, event: str) -> tuple:
    """Returns (subject, body) for a new-outage or restored-outage event."""
    suburb = outage.get("suburb", "your area")

    if event == "new":
        subject = f"Power outage reported in {suburb}"
        lines = [f"A {outage.get('status', 'new').lower()} outage has been reported in {suburb}."]
        if outage.get("reason"):
            lines.append(f"Reason: {outage['reason']}")
        if outage.get("time_started"):
            lines.append(f"Started: {outage['time_started']}")
        if outage.get("estimated_restoration"):
            lines.append(f"Estimated restoration: {outage['estimated_restoration']}")
    else:  # restored
        subject = f"Power restored in {suburb}"
        lines = [f"Power has been restored in {suburb}."]
        if outage.get("actual_restoration"):
            lines.append(f"Restored at: {outage['actual_restoration']}")

    lines.append("")
    lines.append(f"-- {config.SITE_NAME}")
    lines.append("This is an unofficial community tracker, not PNG Power. "
                  "For urgent issues call the National Call Centre on 116.")
    return subject, "\n".join(lines)


def notify_subscribers(outage: dict, subscribers: list, event: str = "new"):
    """
    Sends the appropriate email/SMS to every subscriber for the suburb
    an outage record belongs to. `event` is "new" or "restored".
    Failures for one subscriber don't block the others.
    """
    if not subscribers:
        return

    subject, body = _outage_message(outage, event)

    for sub in subscribers:
        if sub.get("email"):
            body_with_unsub = (
                f"{body}\n\n"
                f"Unsubscribe: {config.SITE_BASE_URL}/unsubscribe/{sub['unsubscribe_token']}"
            )
            send_email(sub["email"], subject, body_with_unsub)
        if sub.get("phone"):
            # SMS bodies should stay short -- skip the unsubscribe footer,
            # keep just the essential line.
            sms_body = body.split("\n")[0]
            send_sms(sub["phone"], sms_body)
