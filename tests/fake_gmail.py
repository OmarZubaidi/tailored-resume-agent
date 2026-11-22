import base64
import json
from datetime import datetime

from resume_agent.guards.rules import GMAIL_SCOPES

ACCOUNT = "you@example.com"


def token_info(scopes=GMAIL_SCOPES, expiry: str = "2999-01-01T00:00:00Z") -> dict:
    return {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": "refresh-token",
        "token": "access-token",
        "expiry": expiry,
        "scopes": list(scopes),
    }


class FakeKeychain:
    def __init__(self, token: dict | None = None) -> None:
        self.items = {}
        if token:
            self.items[("resume_agent", "gmail-token")] = json.dumps(token)

    def get_password(self, service: str, name: str) -> str | None:
        return self.items.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.items[(service, name)] = value


class FakeRequest:
    def __init__(self, result) -> None:
        self.result = result

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(
    message_id: str,
    body: str,
    subject: str = "Your application",
    sender: str = "Acme Health <no-reply@greenhouse.io>",
    received: datetime = datetime(2026, 11, 20, 9, 30),
    mime_type: str = "text/plain",
) -> dict:
    return {
        "id": message_id,
        "internalDate": str(int(received.timestamp() * 1000)),
        "snippet": body[:50],
        "payload": {
            "mimeType": mime_type,
            "headers": [
                {
                    "name": "From",
                    "value": sender,
                },
                {
                    "name": "Subject",
                    "value": subject,
                },
            ],
            "body": {
                "data": encoded(body),
            },
        },
    }


class FakeMessages:
    def __init__(self, messages: list[dict], page_size: int) -> None:
        self.messages = {message["id"]: message for message in messages}
        self.page_size = page_size
        self.queries = []

    def list(self, userId: str, q: str, pageToken: str | None = None):
        self.queries.append(q)
        start = int(pageToken or 0)
        end = start + self.page_size
        page = list(self.messages)[start:end]
        reply = {
            "messages": [
                {
                    "id": message_id,
                }
                for message_id in page
            ],
        }
        if end < len(self.messages):
            reply["nextPageToken"] = str(end)
        return FakeRequest(reply)

    def get(self, userId: str, id: str, format: str):
        return FakeRequest(self.messages[id])


class FakeUsers:
    def __init__(self, account: str, messages: list[dict], page_size: int) -> None:
        self.account = account
        self.fake_messages = FakeMessages(messages, page_size)

    def getProfile(self, userId: str):
        return FakeRequest({"emailAddress": self.account})

    def messages(self):
        return self.fake_messages


class FakeService:
    def __init__(
        self,
        account: str = ACCOUNT,
        messages: list[dict] | None = None,
        page_size: int = 2,
    ) -> None:
        self.fake_users = FakeUsers(account, messages or [], page_size)

    def users(self):
        return self.fake_users
