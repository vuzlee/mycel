"""Send one email, over SMTP. The only way out of this system that reaches a person.

`calendar.py` writes to a calendar nobody replies to; this writes to an inbox, which makes
it the one channel a password reset can use. Nothing is ever read back — there is no IMAP
here, and `agents/tools/mail.py` reads a mailbox for a different reason entirely.

`smtplib` from the standard library rather than a client of its own: sending is one
connection per message and the call is wrapped in `asyncio.to_thread`, so the blocking
socket never touches the event loop that called it.

Optional, and it fails loudly rather than quietly. A calendar event nobody gets is a
cosmetic loss; a reset link nobody gets means an account that cannot be recovered, so a
deployment with no SMTP configured raises here and the route turns the feature off above.
"""

import asyncio
import smtplib
from email.message import EmailMessage

from mycel.core.config import get_settings
from mycel.core.exceptions import MycelError
from mycel.core.logging import get_logger

log = get_logger(__name__)

TIMEOUT_S = 20.0


class MailError(MycelError):
    """The message could not be handed to the server."""


def configured() -> bool:
    """Whether this deployment can send at all. Checked before a feature offers to."""
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_from)


async def send(to: str, subject: str, body: str) -> None:
    """Send one plain-text message, or raise `MailError`."""
    if not configured():
        raise MailError("mail: no SMTP server configured")
    await asyncio.to_thread(_send, to, subject, body)
    log.info("mail sent", extra={"to": to, "subject": subject})


def _send(to: str, subject: str, body: str) -> None:
    """The blocking half. One connection, one message, closed either way."""
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
