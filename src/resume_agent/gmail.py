import json
from pathlib import Path

import httplib2
import keyring
from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from resume_agent.config import Config
from resume_agent.guards.rules import GMAIL_SCOPES

KEYCHAIN_SERVICE = "resume_agent"
KEYCHAIN_TOKEN = "gmail-token"
LOGIN_COMMAND = "resume_agent gmail login --client-file <downloaded JSON>"
SETUP_DOC = "docs/gmail-setup.md"
REQUEST_ERRORS = (HttpError, GoogleAuthError, httplib2.HttpLib2Error, OSError)


class GmailError(Exception):
    pass


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
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_TOKEN, credentials.to_json())


def stored_credentials() -> Credentials:
    token = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_TOKEN)
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
            return request.execute()
        except REQUEST_ERRORS as error:
            raise GmailError(f"Gmail request failed: {error}") from error

    def account(self) -> str:
        return self.execute(self._users.getProfile(userId="me"))["emailAddress"]


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
    require_read_only(credentials)
    account = Mailbox(gmail_service(credentials)).account()
    require_account(account, config)
    store_credentials(credentials)
    return account
