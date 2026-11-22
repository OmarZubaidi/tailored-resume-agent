import json

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


class FakeMessages:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = {message["id"]: message for message in messages}
        self.queries = []

    def list(self, userId: str, q: str, pageToken: str | None = None):
        self.queries.append(q)
        ids = [
            {
                "id": message_id,
            }
            for message_id in self.messages
        ]
        return FakeRequest({"messages": ids} if ids else {})

    def get(self, userId: str, id: str, format: str):
        return FakeRequest(self.messages[id])


class FakeUsers:
    def __init__(self, account: str, messages: list[dict]) -> None:
        self.account = account
        self.fake_messages = FakeMessages(messages)

    def getProfile(self, userId: str):
        return FakeRequest({"emailAddress": self.account})

    def messages(self):
        return self.fake_messages


class FakeService:
    def __init__(self, account: str = ACCOUNT, messages: list[dict] | None = None) -> None:
        self.fake_users = FakeUsers(account, messages or [])

    def users(self):
        return self.fake_users
