"""What a failed provider call means, and keeping keys out of everything a request returns. (Hackathon work, Oct 29.)

    reason(error)          key_rejected, provider_busy or provider_error, for the result's ai object
    describe(error)        the error as one line for a trace, with anything key-shaped masked
    scrub(value, secrets)  the same value with every secret replaced, through dicts, lists and strings
"""
import re

REDACTED = "[redacted]"
# A provider may echo part of a key ("Incorrect API key provided: sk-proj-****abcd"): mask anything key-shaped.
_KEYLIKE = re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-*.]{4,}|[A-Za-z0-9_\-]{40,}")


def reason(error):
    """Why a provider call failed, from its HTTP status. Works for the OpenAI and the Anthropic SDK errors."""
    status = getattr(error, "status_code", None)
    if status in (401, 402, 403):
        return "key_rejected"
    if status in (429, 529):
        return "provider_busy"
    return "provider_error"


def describe(error):
    status = getattr(error, "status_code", None)
    message = getattr(error, "message", None) or str(error)
    return f"{type(error).__name__}{f' ({status})' if status else ''}: {_KEYLIKE.sub(REDACTED, message)[:300]}"


def scrub(value, secrets):
    secrets = [s for s in secrets if s and len(s) >= 8]
    if not secrets:
        return value

    def walk(x):
        if isinstance(x, str):
            for s in secrets:
                x = x.replace(s, REDACTED)
            return x
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [walk(v) for v in x]
        return x

    return walk(value)
