"""The grounded verdict writer: numbered evidence in, a cited "what you'll hear" paragraph out. (Hackathon work, Oct 28.)

    evidence.build(score, answers, fields) -> [Line]      one fact per line, E1..En, no decibels
    writer.write(lines, backend)           -> reply        Muse Spark Open, checked in code, template fallback
    validate.check(reply, lines)           -> [error]      the rules the model cannot skip
    template.write(lines)                  -> reply        deterministic, same schema
    switch.run(lines, request, house)      -> reply + ai   the AI switch: off, the house key, or the caller's own key

`write` below is the whole service in one call, the same response as POST /verdict (CONTRACT.md).
"""
__version__ = "0.1.0"


def write(score, answers=None, fields=None, client=None, writer_choice="auto", ai="on", provider=None, key=None,
          model=None):
    """score + answers + fields -> {evidence, sentences, writer, trace, ai}. `client` is an OpenAI-shaped client to use
    in place of the real one (the eval's scripted client); without one the backend comes from the env, or the template.
    `ai`, `provider`, `key` and `model` are the four X-HushIQ-* headers (switch.py): ai="off" writes the template, a
    `key` runs that provider on the caller's key. Raises evidence.EvidenceError for a score it cannot read, and
    switch.RequestError for a value the headers would refuse."""
    from . import evidence, switch, writer
    lines = evidence.build(score, answers, fields)
    req = switch.request("off" if writer_choice == "template" else ai, provider, key, model)
    house = None if req.ai == "off" or req.key else writer.from_env(None if client is None else {}, client=client)
    return {"evidence": [l.public() for l in lines], **switch.run(lines, req, house=house, client=client)}
