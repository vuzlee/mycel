"""Send one plain-text email over SMTP."""

import asyncio
import smtplib
from email.message import EmailMessage

from mycel.core.config import Settings, get_settings
from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger

log = get_logger(__name__)

TIMEOUT_S = 20.0


class MailError(MycelError):
    """The message could not be handed to the server."""


def configured(settings: Settings | None = None) -> bool:
    """Whether this deployment can send mail."""
    cfg = settings or get_settings()
    return bool(cfg.smtp_host and cfg.smtp_from)


async def send(to: str, subject: str, body: str) -> None:
    """Send one plain-text message, or raise `MailError`."""
    if not configured():
        raise MailError("mail: no SMTP server configured")
    await asyncio.to_thread(_send, to, subject, body)
    log.info("mail sent", extra={"to": to, "subject": subject})


def _send(to: str, subject: str, body: str) -> None:
    """Blocking send: one connection, one message, closed either way."""
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        host = settings.smtp_host or ""
        with smtplib.SMTP(host, settings.smtp_port, timeout=TIMEOUT_S) as server:
            if settings.smtp_starttls:
                server.starttls()
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"mail: {exc}") from exc
