"""The seam: the scripted client, server-sent events, and a stand-in service reached in process and over HTTP."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from hush_eval import adapters as A
from hush_eval import runner

CASE = runner.load_cases(only=["04"])[0]


def test_the_scripted_client_answers_with_a_tool_call():
    client = A.ScriptedClient({"floor": 3})
    resp = client.chat.completions.create(model="m", messages=[], tools=[
        {"type": "function", "function": {"name": "lookup"}}, {"type": "function", "function": {"name": "submit_listing"}}])
    call = resp.choices[0].message.tool_calls[0]
    assert call.function.name == "submit_listing" and json.loads(call.function.arguments) == {"floor": 3}
    plain = client.chat.completions.create(model="m", messages=[])
    assert json.loads(plain.choices[0].message.content) == {"floor": 3} and len(client.calls) == 2


def test_server_sent_events_parse():
    lines = [b"event: turn\n", b'data: {"step": "read"}\n', b"\n", b": keep-alive\n", b"\n",
             b"event: result\n", b'data: {"ok": true,\n', b'data:  "n": 1}\n', b"\n"]
    assert A.read_sse(lines) == [("turn", {"step": "read"}), ("result", {"ok": True, "n": 1})]


@pytest.fixture
def stand_in_reader(tmp_path, monkeypatch):
    """A fake services/agent with the contract's entry point: read(text, photos, client=None, on_turn=None)."""
    svc = tmp_path / "services" / "agent"
    svc.mkdir(parents=True)
    (svc / "standin_reader.py").write_text(
        "import json\n"
        "def read(text, photos, client=None, on_turn=None):\n"
        "    resp = client.chat.completions.create(model='muse-spark-1.3', messages=[{'role': 'user', 'content': text}],\n"
        "                                          tools=[{'type': 'function', 'function': {'name': 'submit_listing'}}])\n"
        "    out = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)\n"
        "    for name, f in out['fields'].items():\n"
        "        for e in f['evidence']:\n"
        "            if e['source'] == 'text' and e['quote'] not in text:\n"
        "                raise ValueError('submit_listing refused: ' + name)\n"
        "    if on_turn: on_turn({'tool': 'submit_listing', 'usage': {'model': 'muse-spark-1.3', 'prompt_tokens': 900, 'completion_tokens': 120}})\n"
        "    return dict(out, score=None, trace=[])\n")
    monkeypatch.setattr(A, "REPO", tmp_path)
    monkeypatch.setitem(A.ENTRYPOINTS, "reader", ("services/agent", ["standin_reader:read"], "HIQ_READER_URL", "/read"))
    yield svc


def test_in_process_mock_runs_the_service_on_the_recorded_model_output(stand_in_reader):
    svc = A.Service("reader", "mock")
    assert svc.transport == "inproc" and "standin_reader:read" in svc.why
    out, meta = svc.call(CASE, **A.reader_inputs(CASE, runner.CASES))
    assert out["fields"]["floor"]["value"] == 3
    assert meta["turns"] == 1 and meta["usage"] == {"muse-spark-1.3": {"prompt_tokens": 900, "completion_tokens": 120}}


def test_in_process_mock_surfaces_the_service_refusing(stand_in_reader):
    bad = json.loads(json.dumps(CASE))
    bad["fixtures"]["reader"]["fields"]["floor"]["evidence"][0]["quote"] = "fourth floor"
    with pytest.raises(ValueError, match="refused: floor"):
        A.Service("reader", "mock").call(bad, **A.reader_inputs(bad, runner.CASES))


def test_without_the_service_mock_mode_replays_and_live_mode_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "REPO", tmp_path)
    monkeypatch.delenv("HIQ_READER_URL", raising=False)
    assert A.Service("reader", "mock").transport == "fixture"
    live = A.Service("reader", "live")
    assert live.transport is None
    with pytest.raises(A.Unreachable):
        live.call(CASE, text="x", photos=[])


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append((self.path, body))
        if self.path == "/read":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            result = CASE["fixtures"]["reader"]
            self.wfile.write(b'event: turn\ndata: {"step": "read the listing"}\n\n')
            self.wfile.write(b"event: result\ndata: " + json.dumps(result).encode() + b"\n\n")
        else:
            payload = json.dumps(CASE["fixtures"]["verdict"]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def log_message(self, *a):
        pass


def test_over_http_the_reader_streams_and_the_verdict_answers_json(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(A, "REPO", tmp_path)
    monkeypatch.setenv("HIQ_READER_URL", url)
    monkeypatch.setenv("HIQ_VERDICT_URL", url)
    try:
        reader = A.Service("reader", "live")
        assert reader.transport == "http"
        out, meta = reader.call(CASE, **A.reader_inputs(CASE, runner.CASES))
        assert out == CASE["fixtures"]["reader"] and meta["turns"] == 1
        verdict, _ = A.Service("verdict", "live").call(CASE, score={}, answers=CASE["answers"], fields={})
        assert verdict["writer"] == "template"
        assert [p for p, _ in server.seen] == ["/read", "/verdict"]
        assert set(server.seen[0][1]) == {"text", "photos"}
    finally:
        server.shutdown()


def test_cost_needs_a_price_for_every_model():
    usage = {"muse-spark-1.3": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}}
    assert A.cost_of(usage, {"muse-spark-1.3": {"input_per_mtok": 1.0, "output_per_mtok": 4.0}}) == 3.0
    assert A.cost_of(usage, {}) is None
