# Authoring agent-read docs

Guidance for writing and placing docs that coding agents load in this repo. Placement
sets who pays for a fact and when:

- **Root `AGENTS.md`** - auto-loaded into every session, so it spends context budget on
  every session whether or not that session touches the topic. Put a fact here only if
  it is both durable and needed in most sessions; keep it terse.
- **A nested `AGENTS.md`** (e.g. `app/AGENTS.md`, `tests/AGENTS.md`) - loaded when a
  session works on a file under that directory, not at launch. Directory-specific facts
  belong here, not in the root.
- **On-demand docs** - read only when a session follows a pointer to them, so the cost
  lands only when the topic is relevant, and length is cheaper than in the auto-loaded
  files. They live in `docs/`. This tier is the home for process detail, step-by-step
  procedures, evidence, examples, and anything durable but rarely needed.

When a fact is borderline, default to an on-demand doc; promoting it up later is cheap.

Bridge these tiers with a pointer: a short link from an auto-loaded file to the
on-demand doc, phrased with the situation that makes it relevant, so the pointer is the
only always-loaded cost and the detail stays on demand. Root `AGENTS.md` already points
to `docs/workflows.md` for before a feature involving states or multistep flows is
designed or changed; copy that pattern for a new doc. Name a new file in kebab-case, and
open it with a one-line purpose, when to read it, and its scope.

## What earns a place

Keep what a session cannot figure out from the code and config in front of it; cut the
rest, because the rest is noise now and drift later.

State each fact once, in its authoritative place, and point to it rather than restate
it. A copy drifts when its source changes, and the worst case is duplication between
`AGENTS.md` and an on-demand doc, since the two get edited at different times. For
example, `docs/workflows.md` states each state machine once; a guide that relies on a
transition points there rather than repeating it.

## Split a topic by volatility and frequency

Placement is not only per file - a single topic can span these tiers. Keep the durable,
often-needed invariant in `AGENTS.md` and move the volatile or rarely-needed detail to
the on-demand doc. It goes the other way too: promote an on-demand fact into `AGENTS.md`
once it turns out to be needed in most sessions. The same split applies under a nested
guide: durable facts for that directory in its `AGENTS.md`, deeper or rarely-needed
material in an on-demand doc.

For example, that features involving states or multistep flows follow documented
workflows is one entry in the root `AGENTS.md`, while the state machines, transitions,
and happy paths themselves - needed only when such a feature is designed or changed -
live in `docs/workflows.md`.

## Do not write situational, drift-prone steps as rules

A step that is both situational (not every change needs it) and drift-prone (its exact
form rots) should not read as a mandatory ritual. State the intent and the kind of
action - for example "run the repo's checks" - rather than the exact command, and defer
the command to its single source.

For example, the root `AGENTS.md` names the lint and test commands once; a doc that
needs the checks run says so in those words and points there, rather than spelling out a
command chain that rots when a recipe is renamed.

## Write for the primary reader

These docs are read mostly by agents; some humans read them too. Present optional
tooling as a convenience, not a requirement - not every contributor has a given CLI
installed. When a list is illustrative, phrase it as open ("for example", "such as")
rather than closed, since an agent may otherwise read it as exhaustive and act only on
the listed cases.

## Before you add or change

When editing an existing doc, apply the same tests: relocate a fact that sits in the
wrong tier, and cut one that no longer earns its place.

1. Could a config or tool enforce this instead of prose - ruff, mypy, markdownlint,
   commitlint, a pre-commit hook, or a setting? If so, prefer that and add at most a
   one-line pointer.
2. Apply the placement tests above: does it earn a place, and which tier does it belong
   in?
3. Put a new on-demand doc in `docs/` and add the inbound pointer from the `AGENTS.md`
   whose readers need it, or nothing will load it.
4. Cold re-read: would a reader with no prior context know when this applies and what to
   check first?
