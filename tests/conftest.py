import json, sys
from pathlib import Path
import pytest, httpx
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from veil.config import Settings, ROOT


@pytest.fixture
def settings(tmp_path):
    return Settings(home=tmp_path / "veil", profile=ROOT / "demo" / "profile.json", api_key="test-key")


class FakeUpstream:
    """Echo-style Token Factory stand-in. Records the exact bytes it received."""

    def __init__(self):
        self.received: list[bytes] = []
        self.reply = None  # callable(body)->dict, optional

    def handler(self, request: httpx.Request):
        raw = request.content
        self.received.append(raw)
        body = json.loads(raw)
        if self.reply:
            data = self.reply(body)
        else:
            last = body["messages"][-1]["content"]
            data = {"id": "chatcmpl-fake", "object": "chat.completion", "model": body["model"],
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": f"echo: {last}"}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}
        if body.get("stream"):
            text = data["choices"][0]["message"].get("content") or ""
            lines = []
            for i in range(0, len(text), 5):  # tiny chunks split tokens across frames on purpose
                lines.append("data: " + json.dumps({"id": "chatcmpl-fake", "model": body["model"],
                             "choices": [{"index": 0, "delta": {"content": text[i:i + 5]}}]}))
            lines.append("data: " + json.dumps({"id": "chatcmpl-fake", "model": body["model"], "choices": [],
                                                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}))
            lines.append("data: [DONE]")
            return httpx.Response(200, content=("\n\n".join(lines) + "\n\n").encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=data)


@pytest.fixture
def fake():
    return FakeUpstream()


@pytest.fixture
def client(settings, fake):
    from fastapi.testclient import TestClient
    from veil.gateway import create_app
    app = create_app(settings, transport=httpx.MockTransport(fake.handler))
    with TestClient(app) as c:
        c.app_ = app
        yield c
