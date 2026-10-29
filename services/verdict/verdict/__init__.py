"""The grounded verdict writer: numbered evidence in, a cited "what you'll hear" paragraph out. (Hackathon work, Oct 28.)

    evidence.build(score, answers, fields) -> [Line]      one fact per line, E1..En, no decibels
    writer.write(lines, backend)           -> reply        Muse Spark Open, checked in code, template fallback
    validate.check(reply, lines)           -> [error]      the rules the model cannot skip
    template.write(lines)                  -> reply        deterministic, same schema
"""
__version__ = "0.1.0"
