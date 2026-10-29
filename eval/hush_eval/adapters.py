"""The seam between the eval and the three services. Each service is reached one of three ways:

    inproc   the service's folder is on this branch and imports: call it in this process
    http     HIQ_<SERVICE>_URL is set: POST to it (the reader answers with server-sent events)
    fixture  neither: replay the output recorded in the case file (mock mode only)

Mock mode (the default) never reaches a model and never needs a key:
    reader   its own mock client (services/agent reader/mock.py) is driven by a responder that answers with the
             case's recorded model output, so the reader's real tools check it: submit_listing refuses an
             unsupported field, read_photo refuses a photo that does not exist. A scorer stand-in returns the
             recorded score, so nothing reaches the city's data.
    adjust   the permit reader's rules reader (client=None), through the same checks as the model.
    verdict  a scripted OpenAI-SDK client playing Muse Spark Open, its draft cut to the writer's own evidence ids.
Live mode passes no stand-ins: each service builds its real client from MODEL_API_KEY or BASETEN_API_KEY.

One Binding per service is the only place that knows its module names and call shape, taken from each service's
CONTRACT.md: services/agent (HIQ-13), services/verdict (HIQ-20) and services/adjust (HIQ-18), as pushed on Oct 28.
HIQ_EVAL_REPO points the eval at another checkout, to run it against a service's unmerged branch.
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

REPO = Path(os.environ.get("HIQ_EVAL_REPO") or Path(__file__).resolve().parents[2])
DEFAULT_ADJUST_CAPS = {"construction": 2.0}   # steps, as services/adjust config.CAPS; its own table wins when importable


class Unreachable(RuntimeError):
    pass


# ---------------------------------------------------------------- a scripted OpenAI-SDK-shaped client (chat API)
class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


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


# ---------------------------------------------------------------- helpers
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


def _post(url, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream, application/json",
                                          "User-Agent": "hush-iq-eval"})
    return urllib.request.urlopen(req, timeout=timeout)


def read_sse(lines):
    """Server-sent events -> [(event, data)]. `data` is parsed as JSON when it can be."""
    events, name, data = [], "message", []

    def flush():
        payload = "\n".join(data)
        try:
            payload = json.loads(payload)
        except ValueError:
            pass
        events.append((name, payload))

    for raw in lines:
        line = (raw.decode() if isinstance(raw, bytes) else raw).rstrip("\r\n")
        if not line:
            if data:
                flush()
            name, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        flush()
    return events


def _import_from(folder, modules):
    """Import `modules` with `folder` on sys.path. (namespace, None) or (None, why)."""
    root = REPO / folder
    if not root.is_dir():
        return None, f"{folder} does not exist on this branch"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    got = {}
    for alias, name in modules.items():
        try:
            got[alias] = importlib.import_module(name)
        except Exception as e:   # a missing dependency or a broken module: say which
            return None, f"{folder} does not import ({name}: {type(e).__name__}: {e})"
    return _Obj(**got), None


# ---------------------------------------------------------------- the bindings
class ReaderBinding:
    """services/agent: reader.loop.read_listing(Listing, client=, scorer=, mode=) -> ("turn", t)..., ("result", r)."""
    name, folder, url_env, path = "reader", "services/agent", "HIQ_READER_URL", "/read"

    def load(self):
        mods, why = _import_from(self.folder, {"loop": "reader.loop", "listing": "reader.listing", "mock": "reader.mock",
                                               "client": "reader.client", "scoring": "reader.scoring"})
        return mods, why or f"in process, {self.folder} reader.loop.read_listing"

    def call(self, mods, case, inputs, mode, on_turn):
        L = mods.listing
        listing = L.Listing(text=inputs["text"], photos=[L.Photo.from_data_url(p, str(i)) for i, p in enumerate(inputs["photos"])],
                            answers=L.Answers.parse(inputs.get("answers") or {}))
        if mode == "mock":
            client, scorer, label = mods.mock.client(reader_responder(mods.mock, (case.get("fixtures") or {}).get("reader") or {})), \
                FixtureScorer(case, mods.scoring.ScoreError), "mock"
        else:
            client, label = mods.client.make_client()
            if label != "live":
                raise Unreachable("live mode, but the reader built its mock client: no MODEL_API_KEY reached it")
            scorer = mods.scoring.HostedScorer()
        result = None
        for kind, data in mods.loop.read_listing(listing, client=client, scorer=scorer, mode=label):
            if kind == "turn":
                on_turn(data)
            elif kind == "result":
                result = data
        return result

    def http_body(self, inputs):
        return inputs


def reader_responder(mock, recorded):
    """Plays the model for the reader's mock client: read the photos the recorded output cites, then submit the
    recorded fields; a field the reader refuses is resubmitted as cant_tell, as a model correcting itself would."""
    fields, observed = recorded.get("fields") or {}, recorded.get("observed") or {}
    photo_fields = {}
    for group in (fields, observed):
        for name, f in group.items():
            for ev in (f or {}).get("evidence") or []:
                src = str(ev.get("source") or "")
                if src.startswith("photo:") and f.get("status") == "read":
                    photo_fields.setdefault(int(src[6:]), {})[name] = {"status": "read", "value": f["value"], "what": ev.get("what")}

    def submit_args(drop=()):
        def strip(f, name):
            if not f or f.get("status") != "read" or name in drop:
                return {"status": "cant_tell", "value": None, "evidence": []}
            ev = [{"source": e["source"], **({"quote": e["quote"]} if e.get("source") == "text" else {})} for e in f["evidence"]]
            value = (f.get("derived") or {}).get("from") or f["value"]   # the model says "top"; the reader adds the count
            return {"status": "read", "value": value, "evidence": ev}
        return {"fields": {n: strip(f, n) for n, f in fields.items()}, "observed": {n: strip(f, n) for n, f in observed.items()}}

    def respond(body):
        i = mock.photo_index(body)
        if i is not None:
            return {"output_text": json.dumps({"fields": photo_fields.get(i, {}), "note": "scripted by the eval"})}
        hist = mock.history(body)
        n = len(hist) + 1
        if photo_fields and not any(c.get("name") == "read_photo" for c, _ in hist):
            return mock.tool_call("read_photo", {"indexes": sorted(photo_fields)}, n)
        refused = set()
        for c, out in hist:
            if c.get("name") == "submit_listing" and isinstance(out, dict):
                refused |= set((out.get("refused") or {}).keys())
        return mock.tool_call("submit_listing", submit_args(refused), n)

    return respond


class FixtureScorer:
    """Stands in for the reader's HostedScorer in mock mode: the recorded location and score, no network."""

    def __init__(self, case, error):
        self.score_body = ((case.get("fixtures") or {}).get("reader") or {}).get("score") or (case.get("fixtures") or {}).get("score")
        self.error = error

    def locate(self, address, text=""):
        addr = (self.score_body or {}).get("address") or {}
        if not addr.get("label"):
            raise self.error(f"no recorded location for {address!r}")
        return {"label": addr["label"], "lat": addr.get("lat"), "lng": addr.get("lng"), "bbl": addr.get("bbl"),
                "bin": addr.get("bin"), "borough": addr.get("borough")}

    def floors(self, bbl):
        """The building's floor count, as the recorded score has it (PLUTO numfloors), for "PH" and "top floor"."""
        return ((self.score_body or {}).get("unit") or {}).get("building_floors") or None

    def score(self, address, floor, position, answers):
        if not self.score_body:
            raise self.error("no recorded score")
        return {"engine": self.score_body.get("engine", "v2"), "url": "fixture", "body": self.score_body}


class AdjustBinding:
    """services/adjust: adjust.permits.read_permits(rows, as_of, client=None) -> {adjustment, readings, ...}."""
    name, folder, url_env, path = "adjust", "services/adjust", "HIQ_ADJUST_URL", "/adjust/permits"

    def load(self):
        mods, why = _import_from(self.folder, {"permits": "adjust.permits", "config": "adjust.config"})
        return mods, why or f"in process, {self.folder} adjust.permits.read_permits"

    def call(self, mods, case, inputs, mode, on_turn):
        client = None
        if mode == "live":
            client = importlib.import_module("adjust.llm").client_from_env()
            if client is None:
                raise Unreachable("live mode, but adjust.llm.client_from_env() found no MODEL_API_KEY")
        return mods.permits.read_permits(inputs["rows"], inputs["as_of"], client=client)

    def caps(self, mods):
        caps = getattr(mods.config, "CAPS", None)
        return {k: float(v) for k, v in caps.items()} if isinstance(caps, dict) and caps else None

    def http_body(self, inputs):
        return {"permits": inputs["rows"], "as_of": inputs["as_of"], "reader": "auto"}


class VerdictBinding:
    """services/verdict: verdict.write(score, answers, fields, client=None) -> {evidence, sentences, writer, trace}.
    Its evidence ids are built per score (verdict.evidence.build), so in mock mode the scripted draft is made against
    them: a recorded model draft when its cites are among the ids built, else one sentence restating each of the
    verdict line, the first rank line and the floor or range line. The writer's checks then run on a real draft."""
    name, folder, url_env, path = "verdict", "services/verdict", "HIQ_VERDICT_URL", "/verdict"
    MODEL_WRITERS = ("muse-spark-open", "muse-spark-1.3")

    def load(self):
        mods, why = _import_from(self.folder, {"verdict": "verdict", "evidence": "verdict.evidence"})
        return mods, why or f"in process, {self.folder} verdict.write"

    def call(self, mods, case, inputs, mode, on_turn):
        kw = dict(inputs)
        if mode == "mock":
            lines = mods.evidence.build(inputs["score"], inputs.get("answers"), inputs.get("fields"))
            kw["client"] = ScriptedClient({"sentences": self.draft(lines, (case.get("fixtures") or {}).get("verdict"))},
                                          model="meta-models/muse-spark-open-1026")
        return mods.verdict.write(**kw)

    def draft(self, lines, recorded):
        ids = {l.id for l in lines}
        if recorded and recorded.get("writer") in self.MODEL_WRITERS and all(
                c in ids for s in recorded.get("sentences", []) for c in s.get("cites", [])):
            return recorded["sentences"]
        picked = []
        for kinds in (("verdict",), ("rank",), ("range", "floor")):
            line = next((l for l in lines if l.kind in kinds), None)
            if line and line not in picked:
                picked.append(line)
        return [{"text": l.text, "cites": [l.id]} for l in picked]

    def http_body(self, inputs):
        return inputs


BINDINGS = {"reader": ReaderBinding, "verdict": VerdictBinding, "adjust": AdjustBinding}


class Service:
    """One service, resolved once per run. `call(case, **inputs)` returns (output, meta)."""

    def __init__(self, name, mode="mock", transport="auto"):
        self.name, self.mode = name, mode
        self.binding = BINDINGS[name]()
        self.mods, why = None, "not tried"
        self.url = os.environ.get(self.binding.url_env)
        if transport in ("auto", "inproc"):
            self.mods, why = self.binding.load()
        if self.mods:
            self.transport, self.why = "inproc", why
        elif transport in ("auto", "http") and self.url:
            self.transport, self.why = "http", f"over HTTP, {self.url}{self.binding.path}"
        elif transport in ("auto", "fixture") and mode == "mock":
            self.transport = "fixture"
            self.why = (f"fixture replay ({why}; {self.binding.url_env} not set)" if transport == "auto"
                        else "fixture replay (forced)")
        else:
            self.transport, self.why = None, f"unreachable: {why}; {self.binding.url_env} not set"

    def caps(self):
        if self.transport == "inproc" and hasattr(self.binding, "caps"):
            caps = self.binding.caps(self.mods)
            if caps:
                return caps, f"{self.binding.folder} config.CAPS"
        return dict(DEFAULT_ADJUST_CAPS), "eval default, the same as services/adjust config.CAPS on Oct 28"

    def call(self, case, **inputs):
        if self.transport is None:
            raise Unreachable(f"{self.name}: {self.why}")
        t0 = time.perf_counter()
        turns = []
        if self.transport == "fixture":
            out = (case.get("fixtures") or {}).get(self.name)
        elif self.transport == "inproc":
            out = self.binding.call(self.mods, case, inputs, self.mode, turns.append)
        else:
            resp = _post(self.url.rstrip("/") + self.binding.path, self.binding.http_body(inputs))
            if "event-stream" in resp.headers.get("Content-Type", ""):
                events = read_sse(resp)
                turns = [d for e, d in events if e == "turn"]
                errors = [d for e, d in events if e == "error"]
                finals = [d for e, d in events if e == "result"]
                if errors and not finals:
                    raise RuntimeError(f"{self.name} streamed an error: {errors[-1]}")
                out = finals[-1] if finals else None
            else:
                out = json.loads(resp.read().decode())
        latency = time.perf_counter() - t0
        return out, {"transport": self.transport, "latency_s": round(latency, 3), "turns": len(turns),
                     "usage": usage_of(out, turns)}


def reader_inputs(case, cases_dir):
    listing = case["listing"]
    return {"text": listing["text"], "photos": [_photo_payload(Path(cases_dir) / p) for p in listing.get("photos") or []],
            "answers": case.get("answers")}


def refusals(out):
    """What a service's own checks refused on the way, as (where, why): the reader's refused submit_listing
    fields and the permit reader's refusals. Shown as notes: a refusal is the checks working, not a failure."""
    found = []
    if not isinstance(out, dict):
        return found
    for t in out.get("trace") or []:
        res = (t or {}).get("result") if isinstance(t, dict) else None
        if isinstance(res, dict):
            for field, why in (res.get("refused") or {}).items():
                found.append((f"{t.get('tool')}.{field}", str(why)))
            if not res.get("refused") and res.get("error") and t.get("tool"):
                found.append((str(t.get("tool")), str(res["error"])))
    for r in out.get("refusals") or []:
        if isinstance(r, dict):
            found.append((f"{r.get('tool')}{'.' + str(r['id']) if r.get('id') else ''}", str(r.get("why"))))
    return found


def usage_of(out, turns=()):
    """Token counts by model, from a result's `usage`, or from its turns' `usage` or `tokens` (the reader's)."""
    found = {}
    model_default = None
    if isinstance(out, dict):   # the permit reader names its model under "reader" ("rules" when no model ran)
        model_default = out.get("model") or (out.get("reader") if out.get("reader") not in (None, "rules", "fixture") else None)

    def add(u, model=None):
        if not isinstance(u, dict):
            return
        m = u.get("model") or model or model_default or "unknown"
        p = u.get("prompt_tokens") or u.get("input_tokens") or u.get("input") or 0
        c = u.get("completion_tokens") or u.get("output_tokens") or u.get("output") or 0
        if not (p or c):
            return
        d = found.setdefault(m, {"prompt_tokens": 0, "completion_tokens": 0})
        d["prompt_tokens"] += int(p)
        d["completion_tokens"] += int(c)

    seen = list(turns) or (list(out.get("trace") or []) if isinstance(out, dict) else [])
    if isinstance(out, dict):
        add(out.get("usage"), out.get("model"))
    for t in seen:
        if isinstance(t, dict):
            add(t.get("usage") or t.get("tokens"), t.get("model"))
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
