import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, text: str) -> None:
    """Sends an email. Called from FastAPI BackgroundTasks so SMTP latency never blocks a response."""
    settings = get_settings()
    if settings.email_backend == "console":
        # Development backend: the message (including any links) is written to the server log.
        log.info("email.console", extra={"to": to, "subject": subject, "body": text})
        return

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        with smtplib.SMTP(settings.smtp_host or "localhost", settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(msg)
        log.info("email.sent", extra={"to": to, "subject": subject})
    except (OSError, smtplib.SMTPException):
        log.exception("email.failed", extra={"to": to, "subject": subject})
