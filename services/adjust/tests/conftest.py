"""Mock mode: no network, no key. The fixtures are real DOB NOW rows, pulled once and scrubbed."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"permits_{name}.json").read_text())


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    """A key in the developer's .env must not turn a mock test live."""
    monkeypatch.setattr("adjust.llm.load_env", lambda *a, **k: None)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


class ScriptedClient:
    """Stands in for openai.OpenAI. Each create() returns the next scripted turn and keeps the messages it was sent.

    A turn is a list of (tool name, arguments) calls, a string for a reply with no tool call ("" for an empty one),
    or an exception to raise."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.kwargs = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(copy.deepcopy(kw["messages"]))
        self.kwargs.append({k: v for k, v in kw.items() if k != "messages"})
        assert self.turns, "the model was called more times than scripted"
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        if isinstance(turn, str):
            msg = SimpleNamespace(content=turn, tool_calls=None)
        else:
            n = len(self.requests)
            msg = SimpleNamespace(content=None, tool_calls=[
                SimpleNamespace(id=f"call_{n}_{i}", type="function",
                                function=SimpleNamespace(name=name, arguments=json.dumps(args)))
                for i, (name, args) in enumerate(turn)])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    def tool_results(self, request_index):
        """The tool results the model saw at the start of that request."""
        return [json.loads(m["content"]) for m in self.requests[request_index] if m["role"] == "tool"]
