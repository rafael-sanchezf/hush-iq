"""One origin for every route (GO-5, hackathon work, Nov 2): the score API and the three services on one host, so the
site and the extension send every call to one base URL.

    GET  /  /v1/score  /v2/score  /v1/raw    packages/model, the score API (prior work, unchanged)
    POST /read  /key-check                   services/agent, the listing reader
    POST /verdict                            services/verdict, the verdict writer
    POST /adjust/permits                     services/adjust, the permit reader
    GET  /health                             this host; /health/reader and /health/verdict are each service's own
    GET  /                                   this host's index: every route and its contract (CLM-5)

Each service keeps its own app for running alone; this one copies their routes and leaves their middleware behind,
so CORS is set once here, for GET and POST. Vercel runs this file (vercel.json); locally, from the repo root:

    uvicorn api.index:app --port 8000
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for part in ("packages/model", "services/agent", "services/verdict", "services/adjust"):
    sys.path.insert(0, str(ROOT / part))

os.environ.setdefault("NOISE_SCORE_CACHE", "/tmp/noise-score-cache")   # the only writable path on a serverless function
if os.environ.get("VERCEL_PROJECT_PRODUCTION_URL"):
    # The reader scores through this same host, whatever its domain, rather than the hosted default.
    os.environ.setdefault("HUSH_SCORE_URL", "https://" + os.environ["VERCEL_PROJECT_PRODUCTION_URL"])

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from adjust import api as adjust_api  # noqa: E402
from noise_score import __version__  # noqa: E402
from noise_score import api as score_api  # noqa: E402
from reader import app as reader_app  # noqa: E402
from verdict import api as verdict_api  # noqa: E402

# Each piece's router, not its app: FastAPI keeps an included router as one entry with no path (0.162), so the permit
# reader gives its APIRouter, the one its own app includes.
PIECES = {"score": score_api.app.router, "reader": reader_app.app.router, "verdict": verdict_api.app.router,
          "adjust": adjust_api.router}
OWN = {"/", "/health"}                                              # answered here, for the whole host
MOVED = {("reader", "/"): "/health/reader", ("verdict", "/health"): "/health/verdict"}

gateway = FastAPI(title="Hush IQ", version=__version__,
              description="The score API and the listing reader, verdict writer and permit reader, on one host.")
# Public and keyless for the caller: any site, and the extension, may call it from the browser. [hackathon]
gateway.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

taken = set()
for piece, router in PIECES.items():
    for route in router.routes:
        path = getattr(route, "path", None)
        if path is None:
            raise RuntimeError(f"{piece} has a route with no path ({type(route).__name__}); list its APIRouter in PIECES")
        if (piece, path) in MOVED:
            gateway.add_api_route(MOVED[piece, path], route.endpoint, methods=sorted(route.methods), tags=[piece])
            continue
        if path in OWN or path.startswith(("/openapi", "/docs", "/redoc")):
            continue
        if path in taken:
            raise RuntimeError(f"{path} is served twice; give the {piece} one a place in MOVED")
        taken.add(path)
        gateway.router.routes.append(route)


REPO = "https://github.com/rafael-sanchezf/hush-iq"
ROUTES = {
    "GET /v2/score": ("the score: address, unit and the renter's answers", "packages/model/README.md"),
    "GET /v1/score": ("the frozen model's score and ingredients", "packages/model/README.md"),
    "GET /v1/raw": ("the city data behind a score", "packages/model/README.md"),
    "POST /read": ("the listing reader: text and photos in, fields with their quotes out, streamed",
                   "services/agent/CONTRACT.md"),
    "POST /key-check": ("checks a caller's own API key without reading anything", "services/agent/CONTRACT.md"),
    "POST /verdict": ("the verdict writer: a paragraph whose every sentence cites the evidence sent",
                      "services/verdict/CONTRACT.md"),
    "POST /adjust/permits": ("the permit reader: construction permits on the tax block, read into a bounded adjustment",
                             "services/adjust/CONTRACT.md"),
    "GET /health": ("this host and its routes", None),
}


@gateway.get("/")
def index():
    """The bare host answers with what it serves, in place of the prototype's page (CLM-5)."""
    return {"service": "Hush IQ", "version": __version__, "repo": REPO,
            "routes": {k: {"what": what, "contract": f"{REPO}/blob/main/{doc}" if doc else None}
                       for k, (what, doc) in ROUTES.items()}}


@gateway.get("/health")
def health():
    return {"ok": True, "version": __version__, "routes": sorted(taken | set(MOVED.values()) | OWN)}


PREFIX = "/api/index"


async def app(scope, receive, send):
    """The entry Vercel and uvicorn run (Vercel takes a module-level `handler` for a request class, so not that name).
    It strips the /api/index prefix if the router adds one."""
    if scope["type"] == "http" and scope.get("path", "").startswith(PREFIX):
        scope = dict(scope)
        scope["path"] = scope["path"][len(PREFIX):] or "/"
        scope["raw_path"] = scope["path"].encode()
    await gateway(scope, receive, send)
