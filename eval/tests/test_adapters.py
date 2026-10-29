"""The seam: the scripted clients, server-sent events, each binding, and the services on this branch."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from hush_eval import adapters as A
from hush_eval import runner

CASE = runner.load_cases(only=["04"])[0]
PHOTO_CASE = runner.load_cases(only=["18"])[0]


def test_the_scripted_client_answers_with_a_tool_call():
    client = A.ScriptedClient({"floor": 3})
    resp = client.chat.completions.create(model="m", messages=[], tools=[
        {"type": "function", "function": {"name": "lookup"}}, {"type": "function", "function": {"name": "submit_verdict"}}])
    call = resp.choices[0].message.tool_calls[0]
    assert call.function.name == "submit_verdict" and json.loads(call.function.arguments) == {"floor": 3}
    plain = client.chat.completions.create(model="m", messages=[])
    assert json.loads(plain.choices[0].message.content) == {"floor": 3} and len(client.calls) == 2


def test_server_sent_events_parse():
    lines = [b"event: turn\n", b'data: {"step": "read"}\n', b"\n", b": keep-alive\n", b"\n",
             b"event: result\n", b'data: {"ok": true,\n', b'data:  "n": 1}\n', b"\n"]
    assert A.read_sse(lines) == [("turn", {"step": "read"}), ("result", {"ok": True, "n": 1})]


# ---------------------------------------------------------------- the reader's responder, on a stand-in of its mock module
def fake_mock():
    def tool_call(name, arguments, n=1):
        return {"output": [{"type": "function_call", "call_id": f"call-{n}", "name": name, "arguments": json.dumps(arguments)}]}

    def history(body):
        items = body["input"]
        outs = {i["call_id"]: json.loads(i["output"]) for i in items if i.get("type") == "function_call_output"}
        return [(i, outs.get(i["call_id"])) for i in items if i.get("type") == "function_call"]

    def photo_index(body):
        return body.get("photo")

    return SimpleNamespace(tool_call=tool_call, history=history, photo_index=photo_index)


def call_of(answer):
    item = answer["output"][0]
    return item["name"], json.loads(item["arguments"])


def test_the_responder_reads_cited_photos_then_submits_and_backs_off_a_refused_field():
    mock = fake_mock()
    respond = A.reader_responder(mock, PHOTO_CASE["fixtures"]["reader"])
    name, args = call_of(respond({"input": [{"role": "user", "content": "Read this listing."}]}))
    assert name == "read_photo" and args == {"indexes": [0, 1]}
    photo0 = json.loads(respond({"photo": 0, "input": []})["output_text"])["fields"]
    assert photo0["ac_units"]["value"] == "window" and photo0["ac_units"]["what"]
    first = {"type": "function_call", "call_id": "call-1", "name": "read_photo", "arguments": "{}"}
    done = {"type": "function_call_output", "call_id": "call-1", "output": "{}"}
    name, args = call_of(respond({"input": [first, done]}))
    assert name == "submit_listing"
    assert args["fields"]["floor"] == {"status": "read", "value": 3, "evidence": [{"source": "text", "quote": "Third-floor"}]}
    assert args["observed"]["wall_material"]["evidence"] == [{"source": "photo:1"}]   # the reading supplies the what
    sub = {"type": "function_call", "call_id": "call-2", "name": "submit_listing", "arguments": "{}"}
    refused = {"type": "function_call_output", "call_id": "call-2", "output": json.dumps({"error": "x", "refused": {"floor": "no"}})}
    _, again = call_of(respond({"input": [first, done, sub, refused]}))
    assert again["fields"]["floor"]["status"] == "cant_tell" and again["fields"]["side"]["status"] == "read"


def test_the_fixture_scorer_stands_in_for_the_city_data():
    class ScoreError(RuntimeError):
        pass
    s = A.FixtureScorer(CASE, ScoreError)
    loc = s.locate("45 Christopher Street")
    assert loc["label"].startswith("45 CHRISTOPHER")
    assert s.score(loc["label"], 3, "front", None)["body"] is CASE["fixtures"]["reader"]["score"]
    with pytest.raises(ScoreError):
        A.FixtureScorer(runner.load_cases(only=["19"])[0], ScoreError).locate("Bank Street")


# ---------------------------------------------------------------- a stand-in verdict writer, in process
def isolate(monkeypatch, package):
    """Hide an already imported package for one test; the test's own copy is dropped afterwards."""
    for name in [m for m in sys.modules if m == package or m.startswith(package + ".")]:
        monkeypatch.delitem(sys.modules, name)

    def drop():
        for name in [m for m in sys.modules if m == package or m.startswith(package + ".")]:
            del sys.modules[name]
    return drop


@pytest.fixture
def stand_in_verdict(tmp_path, monkeypatch):
    """services/verdict's interface: verdict.write(score, answers, fields, client=None) and verdict.evidence.build."""
    pkg = tmp_path / "services" / "verdict" / "verdict"
    pkg.mkdir(parents=True)
    (pkg / "evidence.py").write_text(
        "from types import SimpleNamespace\n"
        "def build(score, answers=None, fields=None):\n"
        "    return [SimpleNamespace(id='E%d' % (i + 1), text=t, kind=k) for i, (t, k) in enumerate(\n"
        "        [('Verdict for you: %s.' % score['verdict'], 'verdict')] + [(i_['label'], 'rank') for i_ in score['ingredients']])]\n")
    (pkg / "__init__.py").write_text(
        "import json\n"
        "def write(score, answers=None, fields=None, client=None, writer_choice='auto'):\n"
        "    from . import evidence\n"
        "    lines = evidence.build(score, answers, fields)\n"
        "    resp = client.chat.completions.create(model='meta-models/muse-spark-open-1026', messages=[],\n"
        "                                          tools=[{'type': 'function', 'function': {'name': 'submit_verdict'}}])\n"
        "    out = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)\n"
        "    ids = {l.id for l in lines}\n"
        "    ok = all(c in ids for s in out['sentences'] for c in s['cites'])\n"
        "    return {'evidence': [{'id': l.id, 'text': l.text} for l in lines], 'sentences': out['sentences'] if ok else [],\n"
        "            'writer': 'muse-spark-open' if ok else 'template'}\n")
    drop = isolate(monkeypatch, "verdict")
    monkeypatch.setattr(A, "REPO", tmp_path)
    yield pkg
    drop()


def test_in_process_mock_drafts_against_the_writers_own_evidence(stand_in_verdict):
    svc = A.Service("verdict", "mock")
    assert svc.transport == "inproc" and "verdict.write" in svc.why
    score = CASE["fixtures"]["reader"]["score"]
    out, meta = svc.call(CASE, score=score, answers=CASE["answers"], fields={})
    assert out["writer"] == "muse-spark-open" and meta["transport"] == "inproc"
    assert out["sentences"][0] == {"text": f"Verdict for you: {score['verdict']}.", "cites": ["E1"]}
    assert [s["cites"] for s in out["sentences"]] == [["E1"], ["E2"]]


def test_a_recorded_model_draft_is_replayed_when_its_ids_exist(stand_in_verdict):
    case = json.loads(json.dumps(CASE))
    case["fixtures"]["verdict"] = {"writer": "muse-spark-open", "sentences": [{"text": "Street first.", "cites": ["E2"]}]}
    out, _ = A.Service("verdict", "mock").call(case, score=case["fixtures"]["reader"]["score"], answers={}, fields={})
    assert out["sentences"] == [{"text": "Street first.", "cites": ["E2"]}]


def test_without_the_service_mock_mode_replays_and_live_mode_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "REPO", tmp_path)
    monkeypatch.delenv("HIQ_READER_URL", raising=False)
    assert A.Service("reader", "mock").transport == "fixture"
    live = A.Service("reader", "live")
    assert live.transport is None
    with pytest.raises(A.Unreachable):
        live.call(CASE, text="x", photos=[])


def test_a_service_that_does_not_import_says_why(tmp_path, monkeypatch):
    (tmp_path / "services" / "adjust" / "adjust").mkdir(parents=True)
    (tmp_path / "services" / "adjust" / "adjust" / "__init__.py").write_text("raise ImportError('no openai here')\n")
    monkeypatch.setattr(A, "REPO", tmp_path)
    drop = isolate(monkeypatch, "adjust")
    monkeypatch.setattr(sys, "path", [p for p in sys.path if not p.endswith("services/adjust")])
    svc = A.Service("adjust", "mock")
    drop()
    assert svc.transport == "fixture" and "does not import" in svc.why


# ---------------------------------------------------------------- over HTTP
class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append((self.path, body))
        if self.path == "/read":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'event: turn\ndata: {"n": 1, "tool": "submit_listing", "tokens": {"input": 900, "output": 100}}\n\n')
            self.wfile.write(b"event: result\ndata: " + json.dumps(dict(CASE["fixtures"]["reader"], model="muse-spark-1.3")).encode() + b"\n\n")
            return
        payload = json.dumps(CASE["fixtures"]["verdict" if self.path == "/verdict" else "adjust"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def test_over_http_the_reader_streams_and_the_others_answer_json(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(A, "REPO", tmp_path)
    for env in ("HIQ_READER_URL", "HIQ_VERDICT_URL", "HIQ_ADJUST_URL"):
        monkeypatch.setenv(env, url)
    try:
        reader = A.Service("reader", "live")
        assert reader.transport == "http"
        out, meta = reader.call(CASE, **A.reader_inputs(CASE, runner.CASES))
        assert out["fields"] == CASE["fixtures"]["reader"]["fields"] and meta["turns"] == 1
        assert meta["usage"] == {"muse-spark-1.3": {"prompt_tokens": 900, "completion_tokens": 100}}
        verdict, _ = A.Service("verdict", "live").call(CASE, score={}, answers=CASE["answers"], fields={})
        assert verdict["writer"] == "template"
        adj, _ = A.Service("adjust", "live").call(CASE, rows=CASE["pull"]["permits"], as_of="2026-10-28")
        assert adj["adjustment"]["cites"] == ["M00000401-I1"]
        assert [p for p, _ in server.seen] == ["/read", "/verdict", "/adjust/permits"]
        assert set(server.seen[0][1]) == {"text", "photos", "answers"}
        assert server.seen[2][1]["as_of"] == "2026-10-28" and len(server.seen[2][1]["permits"]) == 2
    finally:
        server.shutdown()


# ---------------------------------------------------------------- the AI setting: the switch, the provider, the key
def test_the_ai_setting_sends_the_contracts_headers_and_never_shows_the_key():
    key = "sk-fake-not-a-key-0123"
    on = A.AI("on", "openai", "some-model", key)
    assert on.headers() == {"X-HushIQ-AI": "on", "X-HushIQ-Provider": "openai", "X-HushIQ-Key": key, "X-HushIQ-Model": "some-model"}
    assert key not in repr(on) and key not in on.label() and on.whose == "caller"
    assert A.AI("off", "openai", "m", key).headers() == {"X-HushIQ-AI": "off"}
    assert A.AI.for_provider("meta").whose == "house" and A.AI.for_provider(None).headers() == {"X-HushIQ-AI": "on", "X-HushIQ-Provider": "meta"}


def test_a_callers_key_comes_from_the_environment_or_eval_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# set-key.sh\nANTHROPIC_API_KEY='sk-ant-fake-from-file'\n")
    monkeypatch.setattr(A, "EVAL_ENV", env)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert A.env_value("ANTHROPIC_API_KEY", env) == "sk-ant-fake-from-file"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-from-env")
    assert A.env_value("ANTHROPIC_API_KEY", env) == "sk-ant-fake-from-env"
    with pytest.raises(SystemExit) as e:
        A.AI.for_provider("openai")
    assert "OPENAI_API_KEY" in str(e.value)


def test_in_process_a_callers_provider_is_refused_until_the_services_take_one(stand_in_verdict):
    svc = A.Service("verdict", "live", ai=A.AI("on", "anthropic", None, "sk-ant-fake-not-a-key"))
    with pytest.raises(A.Unreachable) as e:
        svc.call(CASE, score=CASE["fixtures"]["reader"]["score"], answers={}, fields={})
    assert "HIQ_VERDICT_URL" in str(e.value) and "sk-ant" not in str(e.value)


class _Echo(BaseHTTPRequestHandler):
    """A permit reader that answers with the headers it was sent, the key among them: the eval must catch it."""
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.seen.append({k.lower(): v for k, v in self.headers.items()})   # header names are case-blind
        body = {"adjustment": None, "readings": [], "echo": self.headers.get("X-HushIQ-Key"),
                "ai": {"mode": "model", "provider": self.headers.get("X-HushIQ-Provider"), "model": "m", "key": "caller",
                       "reason": None, "message": None}}
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def test_over_http_a_provider_run_sends_the_headers_and_a_leaked_key_fails_the_case(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Echo)
    server.seen = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(A, "REPO", tmp_path)
    for env in ("HIQ_READER_URL", "HIQ_VERDICT_URL"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("HIQ_ADJUST_URL", f"http://127.0.0.1:{server.server_port}")
    key = "sk-fake-not-a-key-0123"
    try:
        ai = A.AI("on", "openai", None, key)
        services = {n: A.Service(n, "live", "auto", ai) for n in ("reader", "verdict", "adjust")}
        rec = runner.run_case(CASE, services)
    finally:
        server.shutdown()
    seen = server.seen[0]
    assert seen["x-hushiq-key"] == key and seen["x-hushiq-provider"] == "openai" and seen["x-hushiq-ai"] == "on"
    leaks = [p for p in rec["problems"] if p.check == "ai_switch" and p.hard]
    assert leaks and all(key not in p.message for p in rec["problems"])


# ---------------------------------------------------------------- the real services, once they are on this branch
def test_the_services_on_this_branch_pass_the_mock_run():
    present = [n for n in ("reader", "verdict", "adjust") if A.Service(n, "mock").transport == "inproc"]
    if not present:
        pytest.skip("no service imports on this branch yet; the run replays fixtures")
    res = runner.run("mock")
    hard = [(r["id"], p.where, p.message) for r in res["records"] for p in r["problems"] if p.hard]
    assert hard == [] and res["ok"], hard


def test_cost_needs_a_price_for_every_model():
    usage = {"muse-spark-1.3": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}}
    assert A.cost_of(usage, {"muse-spark-1.3": {"input_per_mtok": 1.0, "output_per_mtok": 4.0}}) == 3.0
    assert A.cost_of(usage, {}) is None


def test_the_services_on_this_branch_run_with_ai_off():
    present = [n for n in ("reader", "verdict") if A.Service(n, "off").transport == "inproc"]
    if len(present) < 2:
        pytest.skip("the reader and the verdict writer are not both on this branch yet")
    res = runner.run("off")
    hard = [(r["id"], p.where, p.message) for r in res["records"] for p in r["problems"] if p.hard]
    assert hard == [] and res["ok"], hard
    assert all(r["cost_usd"] == 0.0 for r in res["records"])
    assert all(r["outputs"]["verdict"]["writer"] == "template" for r in res["records"] if "verdict" in r["outputs"])


def test_every_priced_model_has_both_rates_and_a_dated_id_finds_its_price():
    prices = A.load_prices()
    priced = {m: p for m, p in prices.items() if not m.startswith("_") and p["input_per_mtok"] is not None}
    assert {"muse-spark-1.3", "claude-haiku-5-5", "gpt-6-luna"} <= set(priced)
    assert all(isinstance(p["output_per_mtok"], (int, float)) for p in priced.values())
    usage = {"gpt-6-luna-2026-09-30": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}}
    assert A.cost_of(usage, prices) == 0.6
