import base64
import json
from datetime import date

import pytest
from fake_gmail import (
    ACCOUNT,
    FakeKeychain,
    FakeRequest,
    FakeService,
    encoded,
    gmail_message,
    token_info,
)
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from keyring.errors import KeyringError
from typer.testing import CliRunner

from resume_agent import gmail
from resume_agent.cli import app
from resume_agent.config import Config
from resume_agent.gmail import (
    GmailError,
    Mailbox,
    body_text,
    login,
    open_mailbox,
    parse_message,
    stored_credentials,
)

MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


@pytest.fixture
def config(config_data, write_config) -> Config:
    write_config(config_data)
    return Config(**config_data)


def use_keychain(monkeypatch, token: dict | None = None) -> FakeKeychain:
    keychain = FakeKeychain(token)
    monkeypatch.setattr(gmail.keyring, "get_password", keychain.get_password)
    monkeypatch.setattr(gmail.keyring, "set_password", keychain.set_password)
    return keychain


def use_service(monkeypatch, service: FakeService) -> None:
    monkeypatch.setattr(gmail, "gmail_service", lambda credentials: service)


def test_missing_token_says_how_to_sign_in(monkeypatch):
    use_keychain(monkeypatch)

    with pytest.raises(GmailError, match="gmail login"):
        stored_credentials()


def test_stored_token_must_be_read_only(monkeypatch):
    use_keychain(monkeypatch, token_info(scopes=[MODIFY_SCOPE]))

    with pytest.raises(GmailError, match="read-only"):
        stored_credentials()


def test_valid_token_is_used_as_is(monkeypatch):
    use_keychain(monkeypatch, token_info())

    assert stored_credentials().token == "access-token"


def test_expired_token_is_refreshed_and_stored(monkeypatch):
    keychain = use_keychain(monkeypatch, token_info(expiry="2000-01-01T00:00:00Z"))

    def refresh(credentials, request):
        credentials.token = "new-access-token"

    monkeypatch.setattr(Credentials, "refresh", refresh)

    assert stored_credentials().token == "new-access-token"
    stored = json.loads(keychain.items[("resume_agent", "gmail-token")])
    assert stored["token"] == "new-access-token"


def test_transient_refresh_failure_is_not_called_revoked(monkeypatch):
    use_keychain(monkeypatch, token_info(expiry="2000-01-01T00:00:00Z"))

    def refresh(credentials, request):
        raise RefreshError("backendError")

    monkeypatch.setattr(Credentials, "refresh", refresh)

    with pytest.raises(GmailError, match="Could not refresh Gmail access: backendError"):
        stored_credentials()


def test_keychain_failure_is_a_gmail_error(monkeypatch):
    def locked(service: str, name: str) -> str:
        raise KeyringError("interaction not allowed")

    monkeypatch.setattr(gmail.keyring, "get_password", locked)

    with pytest.raises(GmailError, match="interaction not allowed"):
        stored_credentials()


def test_requests_are_retried():
    request = FakeRequest({"emailAddress": ACCOUNT})

    Mailbox.execute(request)

    assert request.num_retries == 3


def test_body_uses_the_part_charset():
    body = {
        "mimeType": "text/plain",
        "headers": [
            {
                "name": "Content-Type",
                "value": 'text/plain; charset="iso-8859-1"',
            },
        ],
        "body": {
            "data": base64.urlsafe_b64encode("Señor".encode("iso-8859-1")).decode(),
        },
    }

    assert body_text(body) == "Señor"


def test_revoked_token_says_to_sign_in_again(monkeypatch):
    use_keychain(monkeypatch, token_info(expiry="2000-01-01T00:00:00Z"))

    def refresh(credentials, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", refresh)

    with pytest.raises(GmailError, match="expired or was revoked"):
        stored_credentials()


def test_mailbox_must_belong_to_config_email(monkeypatch, config):
    use_keychain(monkeypatch, token_info())
    use_service(monkeypatch, FakeService(account="someone.else@example.com"))

    with pytest.raises(GmailError, match="config.email is you@example.com"):
        open_mailbox(config)


def test_account_match_ignores_case(monkeypatch, config):
    use_keychain(monkeypatch, token_info())
    use_service(monkeypatch, FakeService(account=ACCOUNT.upper()))

    assert isinstance(open_mailbox(config), Mailbox)


def test_message_ids_follow_pages():
    messages = [gmail_message(f"m{number}", "Hello") for number in range(5)]
    service = FakeService(messages=messages, page_size=2)

    assert Mailbox(service).message_ids("in:inbox") == ["m0", "m1", "m2", "m3", "m4"]


def test_message_reads_headers_date_and_text():
    service = FakeService(messages=[gmail_message("m1", "We will not move forward.")])

    email = Mailbox(service).message("m1")

    assert email.sender == "Acme Health <no-reply@greenhouse.io>"
    assert email.subject == "Your application"
    assert email.received == date(2026, 11, 20)
    assert email.text == "We will not move forward."


def multipart(*parts: dict) -> dict:
    return {
        "mimeType": "multipart/mixed",
        "parts": list(parts),
    }


def part(mime_type: str, text: str, filename: str = "") -> dict:
    return {
        "mimeType": mime_type,
        "filename": filename,
        "body": {
            "data": encoded(text),
        },
    }


def test_plain_text_part_wins_over_html():
    payload = multipart(
        multipart(part("text/plain", "Plain body"), part("text/html", "<p>HTML body</p>")),
        part("text/plain", "attachment text", filename="notes.txt"),
    )

    assert body_text(payload) == "Plain body"


def test_html_only_email_is_stripped_to_text():
    html = "<html><head><style>p {}</style></head><body><p>Next&nbsp;round</p></body></html>"

    assert body_text(part("text/html", html)) == "Next round"


def test_empty_body_falls_back_to_snippet():
    message = gmail_message("m1", "")
    message["snippet"] = "Thanks for applying"

    assert parse_message(message).text == "Thanks for applying"


class FakeFlow:
    def __init__(self, scopes: list[str]) -> None:
        self.scopes = scopes

    def run_local_server(self, port: int, open_browser: bool) -> Credentials:
        return Credentials.from_authorized_user_info(token_info(scopes=self.scopes))


def use_flow(monkeypatch, granted: list[str]) -> None:
    monkeypatch.setattr(
        gmail.InstalledAppFlow,
        "from_client_secrets_file",
        lambda path, scopes: FakeFlow(granted),
    )


def test_login_stores_token(monkeypatch, config, tmp_path):
    keychain = use_keychain(monkeypatch)
    use_service(monkeypatch, FakeService())
    use_flow(monkeypatch, list(gmail.GMAIL_SCOPES))

    assert login(tmp_path / "client.json", config) == ACCOUNT
    assert ("resume_agent", "gmail-token") in keychain.items


def test_login_refuses_wrong_account(monkeypatch, config, tmp_path):
    keychain = use_keychain(monkeypatch)
    use_service(monkeypatch, FakeService(account="someone.else@example.com"))
    use_flow(monkeypatch, list(gmail.GMAIL_SCOPES))

    with pytest.raises(GmailError, match="(?s)Signed in to Gmail as someone.else.*connections"):
        login(tmp_path / "client.json", config)
    assert keychain.items == {}


def test_login_refuses_wider_scope(monkeypatch, config, tmp_path):
    keychain = use_keychain(monkeypatch)
    use_service(monkeypatch, FakeService())
    use_flow(monkeypatch, [MODIFY_SCOPE])

    with pytest.raises(GmailError, match="read-only"):
        login(tmp_path / "client.json", config)
    assert keychain.items == {}


def test_login_rejects_bad_client_file(config, tmp_path):
    client_file = tmp_path / "client.json"
    client_file.write_text("{}")

    with pytest.raises(GmailError, match="not a Desktop OAuth client file"):
        login(client_file, config)


def test_login_command_reports_account(monkeypatch, config, tmp_path):
    use_keychain(monkeypatch)
    use_service(monkeypatch, FakeService())
    use_flow(monkeypatch, list(gmail.GMAIL_SCOPES))
    client_file = tmp_path / "client.json"
    client_file.write_text("{}")

    result = CliRunner().invoke(app, ["gmail", "login", "--client-file", str(client_file)])

    assert result.exit_code == 0, result.output
    assert f"Signed in to Gmail as {ACCOUNT}" in result.output
