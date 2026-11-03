"""Every cap and every table the adjustments use, in one place. (Hackathon work, Oct 28.)

Tags like [A2] point at the rules in CONTRACT.md. The frozen model's numbers stay in packages/model; this file only
says how far a model reading may move a source, and the engine applies it.
"""
from noise_score import config as model_config

# ---------------------------------------------------------------- the object [A1]
SOURCES = ("street", "nightlife", "building", "sirens", "construction")   # the engine's five sources
DIRECTIONS = ("louder", "quieter")
MAX_REASON_CHARS = 300

# ---------------------------------------------------------------- caps [A2]
# Size is in steps, never decibels. A source with no cap takes no adjustment yet: 311 text (building) and venue
# hours (nightlife) get theirs when they are built.
CAPS = {"construction": 2}

# Inside the engine only [A5]: one step moves the source's level by this much before it becomes a rank. Measured on
# engine v2's construction ranks between the 20th and 80th percentile of Manhattan, one step moves the rank about 10
# points and the cap about 20 (a step of 3 moved it 15 to 20, too far for one reading).
STEP_LEVEL = {"construction": 2.0}
# A quieter adjustment never takes a source below the level of a block with nothing on it.
LEVEL_FLOOR = {"construction": {w: model_config.CONSTRUCTION_NONE_DB + o
                                for w, o in model_config.CONSTRUCTION_WINDOW_OFFSET.items()}}

# ---------------------------------------------------------------- which permits are read [P1]
# The ones the frozen construction ingredient counts (unexpired, loud work type), plus scaffolds, which it skips
# but which usually mean facade work.
READ_WORK_TYPES = set(model_config.CONSTRUCTION_LOUD_WORK_TYPES) | {"Supported Scaffold", "Suspended Scaffold"}
MAX_PERMITS_READ = 20      # the costliest first when a block has more
# The only permit fields that reach the model, the response or a fixture. DOB rows can carry owner, applicant and
# filing-representative names, phones and emails; none of those is on this list.
PERMIT_FIELDS = ("work_permit", "work_type", "job_description", "house_no", "street_name", "bin",
                 "issued_date", "expired_date", "estimated_job_costs")

# ---------------------------------------------------------------- what a reading may say [P2]
KINDS = ("facade", "interior_renovation", "new_building", "demolition", "scaffold_shed", "other", "cant_tell")
DURATIONS = ("weeks", "months", "years", "cant_tell")   # weeks: under 3 months; months: 3 to 12; years: over 12
MIN_QUOTE_CHARS = 4        # a quote shorter than this proves nothing

# ---------------------------------------------------------------- how far each reading may push [P3]
# Steps of pressure one permit puts on the construction source, by kind and duration. The frozen ingredient already
# counts every loud permit the same; this is the part the count cannot see. A model adjustment may not exceed the
# largest pressure among the permits it cites, in its direction, nor the cap.
PRESSURE = {
    "new_building":        {"weeks": 1, "months": 2, "years": 2, "cant_tell": 2},
    "demolition":          {"weeks": 1, "months": 2, "years": 2, "cant_tell": 1},
    "facade":              {"weeks": 0, "months": 1, "years": 1, "cant_tell": 1},
    "scaffold_shed":       {"weeks": 0, "months": 0, "years": 0, "cant_tell": 0},
    "interior_renovation": {"weeks": -1, "months": -1, "years": 0, "cant_tell": -1},
    "other":               {"weeks": 0, "months": 0, "years": 0, "cant_tell": 0},
    "cant_tell":           {"weeks": 0, "months": 0, "years": 0, "cant_tell": 0},
}
# A quieter adjustment needs at least this share of the permits sent read as quieter than the count says, and none
# louder; a block where most permits say nothing keeps its count.
QUIETER_MIN_SHARE = 0.5

# ---------------------------------------------------------------- the rules reader [P4]
# Used when no model key is set. Duration follows from the kind; the quote is the kind's span.
RULES_DURATION = {"new_building": "years", "demolition": "months", "facade": "months", "scaffold_shed": "months",
                  "interior_renovation": "weeks", "other": "cant_tell"}

# ---------------------------------------------------------------- the model [T1]
MODEL_BASE_URL = "https://api.meta.ai/v1"
MODEL_DEFAULT = "muse-spark-1.3"
MODEL_MAX_TURNS = 8        # model turns per pull, each with any number of tool calls
MODEL_TEMPERATURE = 0.0
# Reasoning tokens count against max_tokens, and a reply cut short comes back with no content and no error, so
# every call gets room: twelve readings with quotes are about 1,500 tokens before any reasoning.
MODEL_MAX_TOKENS = 6000
MODEL_EMPTY_RETRIES = 2    # an empty reply (no text, no tool call) is sent again, at most this many times per pull

# ---------------------------------------------------------------- the AI switch and caller keys [S1 to S5]
# Hackathon work, Oct 29 (HIQ-77). The contract is the shared AI_SWITCH page, copied into CONTRACT.md.
# Base URLs are fixed here, so a caller's key can only go to its own provider. A model id outside a provider's
# list is a 400. The defaults are a first pick: the eval decides and Rafa confirms.
PROVIDERS = {
    "meta": {"base_url": MODEL_BASE_URL, "api": "chat",
             "models": ("muse-spark-1.3",), "default": MODEL_DEFAULT},
    # Tool calls on these models need the Responses API: Chat Completions takes tools only at reasoning effort none.
    "openai": {"base_url": "https://api.openai.com/v1", "api": "responses",
               "models": ("gpt-6.1-sol", "gpt-6-luna", "gpt-6.1-terra", "gpt-6-astra"), "default": "gpt-6.1-sol"},
    "anthropic": {"base_url": "https://api.anthropic.com", "api": "messages",
                  "models": ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"), "default": "claude-opus-5-5"},
}
HOUSE_PROVIDER = "meta"            # the only provider with a house key (MODEL_API_KEY)
HOUSE_AI_DEFAULT = "on"            # HOUSE_AI=off in the environment turns the house key off when the credits end
CALLER_TIMEOUT = 50.0              # seconds per call with a caller's key
CALLER_RETRIES = 0                 # a rate-limited caller key gives no adjustment at once, never a slow retry
OPENAI_EFFORT = "medium"           # reasoning effort on the Responses API
ANTHROPIC_EFFORT = "medium"        # output_config.effort; thinking is adaptive and always on for these models
ANTHROPIC_MAX_TOKENS = 16000       # thinking counts against it, as reasoning does on the other two
ANTHROPIC_FALLBACK = {"claude-opus-5-5", "claude-sonnet-5-5"}   # server-side refusal fallback; Haiku has none
