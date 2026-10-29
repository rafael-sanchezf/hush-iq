"""The seam between the eval and the three services. Each service is reached one of three ways:

    inproc   the service's folder is importable: call its entry function in this process
    http     HIQ_<SERVICE>_URL is set: POST to it (the reader answers with server-sent events)
    fixture  neither: replay the output recorded in the case file (mock mode only)

Mock mode (the default) never reaches a model. In process, the eval hands the service a scripted client that
answers every model call with the case's recorded model output, so the service's own validation (the tools that
refuse an ungrounded field, an uncited sentence, an adjustment over cap) runs on it for free. Live mode passes no
client: the service builds its real one from MODEL_API_KEY or BASETEN_API_KEY.

ENTRYPOINTS is the one place that knows each service's module and function. Until a service has merged, its
candidates are guesses taken from the shared shapes; the first one that imports wins, and `transport_report()`
says which was used and why.
"""
import base64
import importlib
import inspect
import json
import mimetypes
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ENTRYPOINTS = {
    # service: (folder, [module:function candidates], url env var, http path)
    "reader": ("services/agent", ["reader:read", "agent.reader:read", "hiq_agent.reader:read", "app.reader:read"],
               "HIQ_READER_URL", "/read"),
    "verdict": ("services/verdict", ["verdict:write", "writer:write", "verdict.writer:write", "app.verdict:write"],
                "HIQ_VERDICT_URL", "/verdict"),
    "adjust": ("services/adjust", ["adjust:adjust", "permits:adjust", "adjust.permits:adjust", "app.adjust:adjust"],
               "HIQ_ADJUST_URL", "/adjust"),
}
CAPS_ATTR = "CAPS"
DEFAULT_ADJUST_CAPS = {"construction": 15.0}   # rank points; the permit reader's own CAPS wins when importable


class Unreachable(RuntimeError):
    pass


# ---------------------------------------------------------------- a scripted OpenAI-SDK-shaped client
class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self):
        return {k: (v.model_dump() if isinstance(v, _Obj) else v) for k, v in self.__dict__.items()}


class ScriptedClient:
    """Answers `client.chat.completions.create(...)` with a recorded output, the way the OpenAI SDK would.
    If the call offers tools, the answer is a call to the first tool whose name starts with "submit" (else the
    first tool) with the recorded output as its arguments; otherwise it is the output as JSON content."""

    def __init__(self, output, model="scripted"):
        self.output, self.model, self.calls = output, model, []
        self.chat = _Obj(completions=_Obj(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        args = json.dumps(self.output)
        tools = kw.get("tools") or []
        usage = _Obj(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        if tools:
            names = [((t.get("function") or {}).get("name") or t.get("name")) for t in tools]
            name = next((n for n in names if n and n.startswith("submit")), names[0])
            call = _Obj(id=f"call_{len(self.calls)}", type="function", function=_Obj(name=name, arguments=args))
            msg = _Obj(role="assistant", content=None, tool_calls=[call])
            finish = "tool_calls"
        else:
            msg = _Obj(role="assistant", content=args, tool_calls=None)
            finish = "stop"
        return _Obj(id=f"scripted-{len(self.calls)}", model=kw.get("model", self.model), usage=usage,
                    choices=[_Obj(index=0, message=msg, finish_reason=finish)])


# ---------------------------------------------------------------- discovery
def _import_entry(service):
    folder, candidates, _, _ = ENTRYPOINTS[service]
    root = REPO / folder
    if not root.is_dir():
        return None, f"{folder} does not exist on this branch"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    errors = []
    for cand in candidates:
        mod_name, fn_name = cand.split(":")
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as e:
            errors.append(f"{cand}: {e}")
            continue
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            return (mod, fn), f"in process, {folder} {cand}"
        errors.append(f"{cand}: no callable {fn_name}")
    return None, f"{folder} has no entry point ({'; '.join(errors)})"


def _accepts(fn, name):
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind == p.VAR_KEYWORD for p in params.values())


def _photo_payload(path):
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def _post(url, body, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream, application/json",
                                          "User-Agent": "hush-iq-eval"})
    return urllib.request.urlopen(req, timeout=timeout)


def read_sse(lines):
    """Server-sent events -> [(event, data)]. `data` is parsed as JSON when it can be."""
    events, name, data = [], "message", []
    for raw in lines:
        line = raw.decode() if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if not line:
            if data:
                payload = "\n".join(data)
                try:
                    payload = json.loads(payload)
                except ValueError:
                    pass
                events.append((name, payload))
            name, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        payload = "\n".join(data)
        try:
            payload = json.loads(payload)
        except ValueError:
            pass
        events.append((name, payload))
    return events


# ---------------------------------------------------------------- the three services
class Service:
    """One service, resolved once per run. `call(case, mode)` returns (output, meta)."""

    def __init__(self, name, mode="mock", transport="auto"):
        self.name, self.mode = name, mode
        self.entry, why = (None, "not tried")
        url_env = ENTRYPOINTS[name][2]
        self.url = os.environ.get(url_env)
        if transport in ("auto", "inproc"):
            self.entry, why = _import_entry(name)
        if self.entry:
            self.transport, self.why = "inproc", why
        elif transport in ("auto", "http") and self.url:
            self.transport, self.why = "http", f"over HTTP, {self.url}"
        elif transport in ("auto", "fixture") and mode == "mock":
            self.transport = "fixture"
            self.why = f"fixture replay ({why}; {url_env} not set)" if transport == "auto" else "fixture replay (forced)"
        else:
            self.transport, self.why = None, f"unreachable: {why}; {url_env} not set"

    def caps(self):
        if self.transport == "inproc":
            caps = getattr(self.entry[0], CAPS_ATTR, None)
            if isinstance(caps, dict) and caps:
                return {k: float(v) for k, v in caps.items()}, f"{ENTRYPOINTS[self.name][0]} {CAPS_ATTR}"
        return dict(DEFAULT_ADJUST_CAPS), "eval default (the permit reader's CAPS is not importable)"

    def call(self, case, **inputs):
        if self.transport is None:
            raise Unreachable(f"{self.name}: {self.why}")
        recorded = (case.get("fixtures") or {}).get(self.name)
        t0 = time.perf_counter()
        turns = []
        if self.transport == "fixture":
            out = recorded
        elif self.transport == "inproc":
            fn = self.entry[1]
            kw = dict(inputs)
            client = None
            if self.mode == "mock":
                client = ScriptedClient((case.get("fixtures") or {}).get(f"{self.name}_model", _model_view(self.name, recorded)))
                if _accepts(fn, "client"):
                    kw["client"] = client
                else:
                    raise Unreachable(f"{self.name}: {ENTRYPOINTS[self.name][0]} takes no client, so mock mode cannot script it")
            if _accepts(fn, "on_turn"):
                kw["on_turn"] = turns.append
            out = fn(**kw)
        else:
            resp = _post(self.url.rstrip("/") + ENTRYPOINTS[self.name][3], inputs)
            ctype = resp.headers.get("Content-Type", "")
            if "event-stream" in ctype:
                events = read_sse(resp)
                turns = [d for e, d in events if e == "turn"]
                finals = [d for e, d in events if e == "result"]
                out = finals[-1] if finals else None
            else:
                out = json.loads(resp.read().decode())
        latency = time.perf_counter() - t0
        return out, {"transport": self.transport, "latency_s": round(latency, 3), "turns": len(turns),
                     "usage": usage_of(out, turns)}


def _model_view(service, recorded):
    """What the model itself returned, for scripting: the recorded output minus what the service adds."""
    if not isinstance(recorded, dict):
        return recorded
    if service == "reader":
        return {k: recorded[k] for k in ("fields", "position", "observed") if k in recorded}
    if service == "verdict":
        return {"sentences": recorded.get("sentences", [])}
    return recorded


def reader_inputs(case, cases_dir):
    listing = case["listing"]
    return {"text": listing["text"], "photos": [_photo_payload(Path(cases_dir) / p) for p in listing.get("photos") or []]}


def usage_of(out, turns=()):
    """Token counts by model from a result's `usage` or its trace/turns, where the services report them."""
    found = {}

    def add(u, model=None):
        if not isinstance(u, dict):
            return
        m = u.get("model") or model or "unknown"
        d = found.setdefault(m, {"prompt_tokens": 0, "completion_tokens": 0})
        d["prompt_tokens"] += int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
        d["completion_tokens"] += int(u.get("completion_tokens") or u.get("output_tokens") or 0)

    if isinstance(out, dict):
        add(out.get("usage"), out.get("model"))
        for t in out.get("trace") or []:
            if isinstance(t, dict):
                add(t.get("usage"), t.get("model"))
    for t in turns:
        if isinstance(t, dict):
            add(t.get("usage"), t.get("model"))
    return found


def load_prices(path=Path(__file__).resolve().parents[1] / "prices.json"):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def cost_of(usage, prices):
    """Dollars for a usage dict, or None when any model in it has no price on file."""
    total = 0.0
    for model, u in usage.items():
        p = prices.get(model) or {}
        pin, pout = p.get("input_per_mtok"), p.get("output_per_mtok")
        if pin is None or pout is None:
            return None
        total += u["prompt_tokens"] / 1e6 * pin + u["completion_tokens"] / 1e6 * pout
    return round(total, 5)
