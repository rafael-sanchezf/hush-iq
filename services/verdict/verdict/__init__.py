"""The grounded verdict writer: numbered evidence in, a cited "what you'll hear" paragraph out. (Hackathon work, Oct 28.)

    evidence.build(score, answers, fields) -> [Line]      one fact per line, E1..En, no decibels
    writer.write(lines, backend)           -> reply        Muse Spark Open, checked in code, template fallback
    validate.check(reply, lines)           -> [error]      the rules the model cannot skip
    template.write(lines)                  -> reply        deterministic, same schema

`write` below is the whole service in one call, the same response as POST /verdict (CONTRACT.md).
"""
__version__ = "0.1.0"


def write(score, answers=None, fields=None, client=None, writer_choice="auto"):
    """score + answers + fields -> {evidence, sentences, writer, trace}. `client` is an OpenAI-shaped client to use in
    place of the real one (the eval's scripted client); without one the backend comes from the env, or the template.
    Raises evidence.EvidenceError for a score it cannot read."""
    from . import evidence, writer
    lines = evidence.build(score, answers, fields)
    backend = None if writer_choice == "template" else writer.from_env(None if client is None else {}, client=client)
    return {"evidence": [l.public() for l in lines], **writer.write(lines, backend)}
