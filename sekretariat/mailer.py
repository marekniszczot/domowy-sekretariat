"""Outgoing e-mail over SMTP with implicit TLS (D8: a mailbox in the household's domain).

    local / tests:  MemoryMailer (keeps what was sent)
    Cloud Run:      SMTP_HOST, SMTP_USER, SMTP_PASSWORD (secret smtp-password),
                    SMTP_PORT (default 465)

Errors propagate: the caller decides whether a failed send is retried.
"""

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Protocol

SENDER_NAME = "Domowy Sekretariat"


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


class Mailer(Protocol):
    def send(self, to: str, email: Email) -> None: ...


@dataclass
class SmtpMailer:
    host: str
    user: str
    password: str
    port: int = 465
    timeout: float = 30

    def send(self, to: str, email: Email) -> None:
        message = EmailMessage()
        message["From"] = formataddr((SENDER_NAME, self.user))
        message["To"] = to
        message["Subject"] = email.subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=self.user.rpartition("@")[2])
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=self.timeout) as smtp:
            smtp.login(self.user, self.password)
            smtp.send_message(message)


def from_environ(environ) -> SmtpMailer:
    return SmtpMailer(
        host=environ["SMTP_HOST"],
        user=environ["SMTP_USER"],
        password=environ["SMTP_PASSWORD"],
        port=int(environ.get("SMTP_PORT") or 465),
    )


@dataclass
class MemoryMailer:
    sent: list[tuple[str, Email]] = field(default_factory=list)
    fail: bool = False  # simulates an unreachable server

    def send(self, to: str, email: Email) -> None:
        if self.fail:
            raise smtplib.SMTPServerDisconnected("simulated")
        self.sent.append((to, email))
