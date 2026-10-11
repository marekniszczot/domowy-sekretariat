import smtplib

import pytest

from sekretariat import mailer
from sekretariat.mailer import Email, SmtpMailer


class FakeSmtp:
    sessions = []

    def __init__(self, host, port, context, timeout):
        self.host, self.port = host, port
        self.login_args = None
        self.messages = []
        FakeSmtp.sessions.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, message):
        self.messages.append(message)


@pytest.fixture
def smtp(monkeypatch):
    FakeSmtp.sessions = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp


def test_sends_text_and_html_from_the_mailbox(smtp):
    sender = mailer.from_environ(
        {"SMTP_HOST": "mail.example", "SMTP_USER": "box@example.pl", "SMTP_PASSWORD": "pw"}
    )
    sender.send("jan@example.com", Email("Jutro termin: Bank", "tekst ąę", "<p>html</p>"))

    [session] = smtp.sessions
    assert (session.host, session.port, session.login_args) == (
        "mail.example",
        465,
        ("box@example.pl", "pw"),
    )
    [message] = session.messages
    assert message["From"] == "Domowy Sekretariat <box@example.pl>"
    assert message["To"] == "jan@example.com"
    assert message["Subject"] == "Jutro termin: Bank"
    assert message["Message-ID"].endswith("@example.pl>")
    assert [part.get_content_type() for part in message.iter_parts()] == ["text/plain", "text/html"]
    assert message.get_body(("plain",)).get_content() == "tekst ąę\n"


def test_port_from_environment(smtp):
    sender = mailer.from_environ(
        {"SMTP_HOST": "h", "SMTP_USER": "u@d.pl", "SMTP_PASSWORD": "p", "SMTP_PORT": "2465"}
    )
    assert sender == SmtpMailer("h", "u@d.pl", "p", 2465)
