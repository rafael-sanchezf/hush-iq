# Hush IQ, for Claude sessions in this repo

A noise score for any NYC apartment, for the way you sleep, served to listing sites as an API. Public
monorepo, entered in the Meta Global AI Developer Hackathon (Oct 26 to Nov 4, 2026). Read `HACKATHON.md`
before any change: it is the line between prior work and hackathon work, and every commit keeps it true.

## Layout

```
apps/ios        SwiftUI app and NoiseKit (prior work; the class repo's history stays on GitLab)
apps/web        the website (hackathon)
packages/model  the noise model and FastAPI (prior work, frozen: model.py, baseline.py, sources.py never change)
services/agent  the Meta-model layer (hackathon)
HACKATHON.md    what existed at kickoff, what was built after, which model did what
FEEDBACK.md     every rough edge met in the Meta Model API and the partner tools, for the submission form
```

## Rules

1. **New work only, and say so.** The score math (M1 to M13 in `packages/model/DECISIONS.md`), the eight
   datasets and the Manhattan baseline are frozen. New features are a layer on top. Each lands with a line
   in `HACKATHON.md` naming the model, the host and the commit.
2. **The model cannot invent a source.** Every model output that reaches a renter is validated against the
   evidence it was sent: citations as an enum, adjustments within caps, extracted fields with a quoted span.
   The checks live in the tools, not in the prompt, so the agent cannot skip them.
3. **Meta models through the OpenAI SDK** at `https://api.meta.ai/v1` (`MODEL_API_KEY`), default
   `muse-spark-1.3`; open weights as `meta-models/muse-spark-open-1026` on Baseten
   (`BASETEN_API_KEY`). Keys live in `packages/model/.env` and `services/agent/.env`, never in git.
4. **Nothing personal in the public tree.** No course codes, no university identifiers, no keys. The user
   agent names this repository.

## The board

This repo files to the Jira project **HIQ** on `rafasanchezfajardo12.atlassian.net`
(`~/code/verso/scripts/jira/jira`, works from any directory, token in `~/code/verso/.env`; the rules in
`~/.claude/JIRA.md`). One Epic per piece in `HACKATHON.md`; a branch is `HIQ-12-short-name` and the PR
title starts with the key. Rafa's items read "Verb: object (N min)" and sit in Ready (To Do until the board
has the column), never Backlog. A question only he can answer is `jira ask`, never a guess. Close every
session with each touched card in its true state.
