import base64
import codecs
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

import httplib2
import keyring
from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from keyring.errors import KeyringError

from resume_agent.config import Config
from resume_agent.guards.rules import GMAIL_SCOPES

KEYCHAIN_SERVICE = "resume_agent"
KEYCHAIN_TOKEN = "gmail-token"
LOGIN_COMMAND = "resume_agent gmail login --client-file <downloaded JSON>"
SETUP_DOC = "docs/gmail-setup.md"
REQUEST_ERRORS = (HttpError, GoogleAuthError, httplib2.HttpLib2Error, OSError)
REQUEST_RETRIES = 3
REVOKED_GRANT = "invalid_grant"
CONNECTIONS_URL = "https://myaccount.google.com/connections"
CHARSET = re.compile(r"charset=\"?([\w.:-]+)", re.IGNORECASE)
DEFAULT_CHARSET = "utf-8"
HIDDEN_TAGS = frozenset({"head", "script", "style"})
WHITESPACE = re.compile(r"\s+")


class GmailError(Exception):
    pass


@dataclass(frozen=True)
class Email:
    id: str
    sender: str
    subject: str
    received: date
    text: str


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in HIDDEN_TAGS:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in HIDDEN_TAGS and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def html_text(html: str) -> str:
    extractor = TextExtractor()
    extractor.feed(html)
    extractor.close()
    return WHITESPACE.sub(" ", " ".join(extractor.parts)).strip()


def walk_parts(payload: dict) -> Iterator[dict]:
    yield payload
    for part in payload.get("parts", []):
        yield from walk_parts(part)


def part_charset(part: dict) -> str:
    match = CHARSET.search(header(part, "Content-Type"))
    if not match:
        return DEFAULT_CHARSET
    try:
        return codecs.lookup(match.group(1)).name
    except LookupError:
        return DEFAULT_CHARSET


def decoded_body(part: dict) -> str:
    data = part.get("body", {}).get("data", "")
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode(part_charset(part), errors="replace")


def body_text(payload: dict) -> str:
    inline = [part for part in walk_parts(payload) if not part.get("filename")]
    plain = [decoded_body(part) for part in inline if part.get("mimeType") == "text/plain"]
    if any(text.strip() for text in plain):
        return "\n".join(plain).strip()
    html = [decoded_body(part) for part in inline if part.get("mimeType") == "text/html"]
    return "\n".join(html_text(text) for text in html).strip()


def header(payload: dict, name: str) -> str:
    wanted = name.lower()
    found = (item["value"] for item in payload.get("headers", []) if item["name"].lower() == wanted)
    return next(found, "")


def parse_message(message: dict) -> Email:
    payload = message.get("payload", {})
    return Email(
        id=message["id"],
        sender=header(payload, "From"),
        subject=header(payload, "Subject"),
        received=datetime.fromtimestamp(int(message["internalDate"]) / 1000).date(),
        text=body_text(payload) or message.get("snippet", ""),
    )


def require_read_only(credentials: Credentials) -> None:
    granted = set(credentials.scopes or ())
    if granted != set(GMAIL_SCOPES):
        raise GmailError(
            f"Gmail access must be read-only ({', '.join(GMAIL_SCOPES)}), got: "
            f"{', '.join(sorted(granted)) or 'none'}"
        )


def require_account(account: str, config: Config) -> None:
    if account.lower() != config.email.lower():
        raise GmailError(
            f"Signed in to Gmail as {account}, but config.email is {config.email}. "
            "Sign in with that account, or update config.email."
        )


def store_credentials(credentials: Credentials) -> None:
    try:
        keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_TOKEN, credentials.to_json())
    except KeyringError as error:
        raise GmailError(f"Could not save the Gmail token to the Keychain: {error}") from error


def stored_credentials() -> Credentials:
    try:
        token = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_TOKEN)
    except KeyringError as error:
        raise GmailError(f"Could not read the Gmail token from the Keychain: {error}") from error
    if not token:
        raise GmailError(f"Not signed in to Gmail. Run `{LOGIN_COMMAND}`; see {SETUP_DOC}.")
    try:
        credentials = Credentials.from_authorized_user_info(json.loads(token))
    except ValueError as error:
        raise GmailError(
            f"The Keychain's Gmail token is unreadable. Run `{LOGIN_COMMAND}`."
        ) from error
    require_read_only(credentials)
    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            if REVOKED_GRANT not in str(error):
                raise GmailError(f"Could not refresh Gmail access: {error}") from error
            raise GmailError(
                f"Gmail sign-in expired or was revoked. Run `{LOGIN_COMMAND}` again."
            ) from error
        except TransportError as error:
            raise GmailError(f"Could not reach Google to refresh Gmail access: {error}") from error
        store_credentials(credentials)
    return credentials


class Mailbox:
    """Read-only Gmail access: the only calls the agent makes."""

    def __init__(self, service) -> None:
        self._users = service.users()

    @staticmethod
    def execute(request) -> dict:
        try:
            return request.execute(num_retries=REQUEST_RETRIES)
        except REQUEST_ERRORS as error:
            raise GmailError(f"Gmail request failed: {error}") from error

    def account(self) -> str:
        return self.execute(self._users.getProfile(userId="me"))["emailAddress"]

    def message_ids(self, query: str) -> list[str]:
        ids, page = [], None
        while True:
            request = self._users.messages().list(userId="me", q=query, pageToken=page)
            reply = self.execute(request)
            ids += [message["id"] for message in reply.get("messages", [])]
            page = reply.get("nextPageToken")
            if not page:
                return ids

    def message(self, message_id: str) -> Email:
        request = self._users.messages().get(userId="me", id=message_id, format="full")
        return parse_message(self.execute(request))


def gmail_service(credentials: Credentials):
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def open_mailbox(config: Config) -> Mailbox:
    mailbox = Mailbox(gmail_service(stored_credentials()))
    require_account(mailbox.account(), config)
    return mailbox


def login(client_file: Path, config: Config) -> str:
    try:
        flow = InstalledAppFlow.from_client_secrets_file(client_file, scopes=list(GMAIL_SCOPES))
    except (OSError, ValueError) as error:
        raise GmailError(f"{client_file} is not a Desktop OAuth client file: {error}") from error
    credentials = flow.run_local_server(port=0, open_browser=True)
    try:
        require_read_only(credentials)
        account = Mailbox(gmail_service(credentials)).account()
        require_account(account, config)
    except GmailError as error:
        raise GmailError(f"{error}\nRemove the refused grant at {CONNECTIONS_URL}.") from error
    store_credentials(credentials)
    return account
