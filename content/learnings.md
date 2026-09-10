# AI & Coding Learnings

Everything worth knowing that came out of roughly two months of building with LLMs,
agents, retrieval and generation pipelines — across several unrelated projects.

**What this file is.** A grouped, project-independent digest of measured findings,
failure modes and design rules. Grouped by what a developer or technically interested
reader would actually want out of it, not by project or chronology.

**Ground rules for this document**

- No employer, client, product or internal-system names. No internal class, table or
  module names. Where a use case needs describing, it is described generically
  ("a code-audit pipeline", "a legal-document search case study", "an interview presentation").
- Numbers are measured unless labelled as estimated. Where a figure was later found
  wrong, both the wrong number and the correction are kept — the correction is usually
  the more useful half.
- Public tools and generic technologies are named where they matter to the lesson, and
  described by role where they do not ("a vector store", "the ASR model"). Nobody's stack is
  a secret; it is just rarely the interesting part.

The projects behind it, described only by shape:

| # | Shape of the project |
|---|---|
| A | Multi-agent document-generation pipeline (job posting → tailored, verified PDF) |
| B | Multi-agent code-audit / review pipeline over a large PHP codebase |
| C | Retrieval platform (hybrid RAG over heterogeneous enterprise sources, with an evaluation harness) |
| D | Offline audiobook pipeline (TTS + ASR verification loop) |
| E | Interactive technical presentation generation (single-page HTML decks) |
| F | Quantitative signal/backtesting harnesses |
| G | A design-study for legal-document search on a cloud platform |

---

## 1 — What an agent run actually costs

The single most consequential thing learned. Almost every cost intuition was wrong,
and measuring was cheap.

### 1.1 Cost is quadratic in turns, not linear in tokens

Before every API request an agent is re-sent its whole history. What it read in turn 3
is billed again in turns 4…T. So for a context growing by δ per turn:

```
Input(T) = Σ (C₀ + i·δ)  =  T·C₀ + δ·T²/2
```

`δ·T²/2` dominates: **working twice as long costs roughly four times as much.**

Measured on one 17-agent audit run:

| | final context | billed input | replay factor |
|---|---|---|---|
| whole run | 1.41M | 30.93M | **21.95×** |
| the longest single agent (94 turns) | 171k | 9.89M | **57.75×** |
| verifiers (17–43 turns) | 67–103k | 0.88–2.83M | 12–28× |

Output was **355k against 30.9M input — 1.1 % of the billed volume.**

**The lever order that falls out:**

1. **fewer turns** (acts on the quadratic term)
2. **smaller tool outputs** = smaller δ (also quadratic)
3. **smaller boot context** C₀ (linear only)
4. model tier and prompt shortening (acts on ~1–2 % of the bill)

The corollary is worth memorising: **the price of one tool result is `b · (T − i)`.**
A 22 KB file read in turn 3 of a 43-turn agent is an 880 KB item, not a 22 KB item.

### 1.2 Everyone optimises output length. Output is noise.

Output was 1.1 % of the bill in project B, and ~17 % of a (differently shaped) cost
split in project A. Prompt shortening — the intervention everyone reaches for first —
lands on the smallest term in the equation. In a controlled before/after of a finding-
format compression at identical tiers with a cold cache, the total moved
$14.90 → $16.24 (+9 %) — i.e. **no detectable effect**, well inside the noise floor.

### 1.3 What you load early, you pay for on every later turn

In project A one 79 KB fact-base JSON was read at turn 2 by three subagents and re-sent
on every subsequent turn:

```
agent 1:  29,300 tok × 31 later turns  =  908,300
agent 2:  29,300 × 20                  =  586,000
agent 3:  29,300 × 14                  =  410,200
                              ≈ 1.90M of 3.21M cache-read  →  59 %
```

One file was 59 % of a run's token bill — not because it was read often, but because it
was read *early*.

Fixes that worked: minified, phase-scoped digests instead of the full file; **paths
injected instead of contents**; and merging agents that shared context.

### 1.4 A cost share is not a lever

Token classes for one run at write 1.25× / read 0.1×:

| | tokens | share of tokens | share of the bill |
|---|---|---|---|
| raw input | 21,478 | 0.1 % | 0.4 % |
| cache **write** | 2,266,379 | 10.3 % | **58.7 %** |
| cache read | 19,755,411 | 89.6 % | 40.9 % |

"Writes are 58.7 % of the bill" invites the conclusion that moving text into a shared
cached prefix is a big lever. It is not: the text actually movable was ~650 tokens per
agent against 2.27M write tokens — sharing it across 11 agents is worth **~0.1 %**.
Even hoisting a 45 KB evidence pack into the prefix is **~1.9 %**.

**Before costing any caching or prompt-layout change, compute what fraction of the
volume the text you are moving actually is.**

### 1.5 Injected context is the parent's *output* tokens

A rule of "inject file contents into subagent prompts, never paths" makes the
orchestrator pay, in the most expensive column there is. In one run the orchestrator's
cost share jumped 28 % → 49 % between two otherwise identical runs, purely because
standards files were pasted into subagent prompts instead of referenced. 27.1k output
tokens on the main thread, most of it prompt text typed for someone else to read.

**Content-injection is ~20× more expensive than passing a path** — and for a large
structured fact base it is also *less* accurate, because hand-copying a single source of
truth three times is how a date quietly becomes wrong. The rare case where the cheap
option and the correct option are the same one.

### 1.6 Have the model emit a delta, not a document

Two independent measurements, same conclusion:

- **Document generation (project A).** The generator rewrote an entire ~9.8 KB content
  JSON (~2,970 output tokens) to change the summary, a skill order and a few bullets.
  Emitting a patch of changed fields only: ~600–2,000 tokens.
- **Boilerplate.** A letter generator wrote all 5.6 KB of an HTML document, of which
  ~2 KB was byte-identical on every single run. Moved into a template; the model now
  emits only the holes. ~1,730 → ~1,215 output tokens.

Output costs ~5× input on every model *and* is 100 % of the serial wall clock (input is
one prefill; output is generated token by token). Retyping stable data is the most
expensive habit available.

**And it is a correctness win, not only a cost one: a patch cannot corrupt a date it
never mentions.** Everything the patch does not name is provably identical to the base.

**Honest correction:** the first published saving was −80 %, measured on a *synthetic*
patch that changed one bullet set. A real tailoring run does far more work: the real
patch was 7,175 B against a 9,225 B document — **−22 %, not −80 %**. Reducing the
skills section to a reorder-by-reference recovered another ~375 tokens, taking it to
~−34 %. Lesson: **measuring a proxy you chose because it was easy to build will
flatter the change.**

### 1.7 Parallelism is only free when the branches do not share context

Two generation agents ran in parallel and shared ~95 % of their input (same digest, same
standards, same brief) to produce ~600 and ~1,215 tokens of delta each. Merging them
into one agent:

| | before | after |
|---|---|---|
| digest loads per run | 3 | 2 |
| digest tokens per run | ~58.6k | ~37.7k |

**−36 %, and ~19k of the ~21k came from the merge**, not from the context-scoping work
done alongside it. Paying a 19,000-token context load to parallelise ten seconds of
typing is a bad trade — and it only became a bad trade *after* the delta change of §1.6
made each branch cheap.

### 1.8 Horizontal batching: derive the break-even before running the experiment

For an agent handling `k` items in `T = t₀ + k·t₁` turns, the cost-optimal batch size is

```
k* = √(t₀² + 2·t₀·C₀/δ) / t₁
```

Filled in with the measured C₀ and δ of every agent in the pipeline, **`k* < 1` for
every single one** — one item per agent beats any batch, because δ is high relative to
C₀. Batching would only start to pay if δ dropped by an order of magnitude, at which
point the δ reduction is itself the saving.

Two optimisations (batching, agent merging) were ruled out on paper in an afternoon and
the arithmetic was later confirmed by the runs. **Derive the break-even first.**

### 1.9 Vertical merging: the agents you can merge are the ones that cost nothing

| Merge candidate | measured share of run | verdict |
|---|---|---|
| pre-screen → validate | 0.3 % | not worth losing "structurally cannot decide" |
| stage 1 + stage 2 | ~42 % of agents | **mechanically impossible** — stage 2's value *is* its ignorance of stage 1 |
| shrink a 3-agent consensus panel to 1 | 8 % | destroys the majority principle |

**Generalised: what is expensive is expensive *because* it is independent, and
independence is not divisible.**

### 1.10 The human is usually the critical path

First profiling of a document pipeline: 70 minutes wall clock. The first diagnosis
("a chatty agent burning tool calls") was plausible and wrong.

| Phase | Span | Model time | Real tool exec | Blocked on approval |
|---|---:|---:|---:|---:|
| 1 | 2m14s | 2m14s | 0.4s | 0 |
| 2a | 11m18s | 3m33s | 0.4s | 7m45s |
| 2b | 27m08s | 4m24s | 1m08s | 21m36s |
| 3 | 40m42s | 1m00s | 21.8s | 39m20s |
| **Sum** | **1h21m** | **11m11s** | **1m30s** | **1h08m** |

**84 % of the run was five permission prompts.** Model latency was 14 %. Optimising
tokens first would have been the wrong project entirely.

After fixing the friction: critical path **70m04s → 5m19s (13.2×)** with model time
barely moving (11m11s → 8m03s). The generation was never the bottleneck.

Two distinct causes, easy to conflate:

1. **The command's own questions** — it asked for the input and for two scope decisions
   *unconditionally*, even when both were already answerable from the conversation.
   It asked because it was told to.
2. **Harness permission prompts** — an allowlist of ~90 **exact-match** entries,
   accumulated one approval at a time, including previous runs' full command strings
   with a slug baked into the path. Every run produces new argument combinations, so
   nothing matched and everything re-prompted. **An allowlist of literals cannot
   generalise; scope it to the stable shapes instead.**

### 1.11 Two known-good ratios

- **A deterministic render phase on the cheapest model tier came to 0.5–0.6 % of run
  cost, across three consecutive runs — while producing 100 % of the files the recipient
  actually opens.** The expensive agents produce text for other agents to read.
- **Pipeline cost is stable enough to budget.** Two runs on entirely different inputs:
  $3.94 and $4.00 — stable to ~1.5 %. Once a workflow's cost is a known quantity you
  can start arguing about whether it is worth it, which is the more interesting
  question.
- **Editing beats regenerating when facts change but structure does not:** a three-
  sentence correction pass cost $1.10 against $4.00 for a full re-run — ~27 %.

### 1.12 Measuring is not free

One session spent **$9.72 after the pipeline finished**, on the conversation analysing
what the pipeline had cost. The pipeline was $3.94. Measurement cost 2.5× the thing
being measured. Worth it once; not worth it every run — which is the argument for
putting the measurement in a script.

---

## 2 — Where the model belongs, and where code belongs

If there is one architectural idea that paid off everywhere, it is this boundary.

> **The model emits only what is a judgement call. Everything mechanical — merging,
> templating, dating, page-fitting, text hygiene, file naming, verification — is
> deterministic code.**

That sounds obvious. It was not how any of these pipelines started.

### 2.1 The LLM decides; a script executes

Four steps in project B were LLM agents doing mechanical work. Each became a committed
script, with the decision reduced to a small plan the model emits:

| Step | As an agent | As a script |
|---|---|---|
| split findings into per-item files | **~99k tokens, ~8 min** | `awk`/`sed`, seconds, ~0 tokens, byte-identical by construction |
| group findings | rewrite the whole file — O(file size), can reword or drop | model returns a plan (ids + titles); a script moves blocks by anchor — O(number of items) |
| apply verdicts | a frontier-model agent rewriting the file | anchor-based script driven by a cheap runner |
| verify the output | a fresh reviewer agent | a script proving total conservation — an *equality*, not an opinion |

Three reasons the split holds, all structural rather than economic:

1. **Content drift.** A model that retypes items can reword, truncate or silently drop
   one. **An item whose wording changed after verification is no longer the item that
   was verified.**
2. **Cost scales with the wrong thing.** Rewriting is O(file size); planning is
   O(items), and the deciding input is one line each.
3. **Structure is checkable.** "Every id placed exactly once", "no invented id", count
   conservation — a script can *prove* these and refuse to write. A reviewer agent can
   only opine.

The enabler that makes it both cheap and correct: **compression at authoring time.**
The upstream agent writes a canonical tag into each item's heading, so the downstream
step reads headings only and never opens a body.

### 2.2 Anything the machine can compute, the machine should compute

A generated letter's date was written by the model. A model that writes a date can write
a wrong one — and a locale-dependent one is wrong on someone else's machine. Now
computed in code with hardcoded month names.

### 2.3 Enforcement-by-iteration is invisible in the output and expensive in the transcript

A one-page fit rule was enforced by the agent: write → render → check → shorten →
render. In one measured run that was **7 `Edit` calls**; in the worst, **42 turns and
27.1 minutes on one page of text with 14 edits.** Each edit re-read ~44k tokens of
context, so shortening one page cost ~300k read tokens.

The PDF looks identical either way. **Only the transcript reveals that the pipeline is
enforcing a deterministic property by iteration.** Metrics derived from artifacts would
have missed it entirely.

Replaced by a capped scaling ladder in code that fails loudly below the floor rather
than shipping something cramped. Same phase: **40m42s → 1.16 s.**

But the honest mechanism is three things, not one: approval prompts 2 → 1, model time
1m00s → ~10s, and verification moved from an LLM checklist into 12 assertions. **A
number without a mechanism is a story.**

### 2.4 A docstring that says a problem is solved is a claim, not evidence

The fit function had guaranteed one page since the day it was written, and its docstring
said the agent loop had been removed. **The agent's prompt still ordered the loop**, so
it kept running. Both files were internally consistent; the system was not.

Related, from the same audit: three files disagreed about one decision — the
orchestrator said *inject the data*, the agent files said *never read the data*, and the
transcripts showed agents reading it **twice**. **Contradictions do not resolve; they
get resolved by whichever agent happens to run.**

### 2.5 Dead correct tooling is worse than missing tooling

A digest generator existed, was correct, had the exact measurement of the bottleneck in
its docstring — and was **referenced by nothing**. So the cost it was built to remove
was paid in full every run, *and* its stale output on disk was a live correctness risk
(built two days before the source file it was derived from was last modified).

### 2.6 Route by mechanism, not by topic

One task — *"every mutation must reach the audit log"* — sounded like a single coherent
job. It contained 18 findings needing three completely different methods:

| Findings | What it actually needed |
|---|---|
| 9 of 18 | a **static rule** — the remedy is identical and grep-able for each |
| 1 | tool/reduce |
| 1 | **judgement** — attribution lost across a queue boundary; no grep reaches it |
| 1 | judgement + a semantic call on which columns count as secret |
| 3 | judgement, closest to *counterfactual* reasoning (dormant branches) |

Routing it all to the cheap mechanical method loses the last five findings. Routing it
all to judgement — which is what happened — **pays a frontier-model sweep to find nine
models missing an annotation that a ~30-line static rule catches forever.** Both errors
are silent.

There was also a structural inversion underneath: the stage that establishes the
mechanism ran *after* the stage that picked the route. **The information needed to route
was produced by a stage that routing gated.** Fixed by enumerating subtasks first and
dispatching one child run per subtask when they do not share a method.

### 2.7 The escalation ladder, in order

Worth stating as a default posture, because every step up costs money and reliability:

```
deterministic solution → simple prompt → few-shot → context engineering →
retrieval → reranking → workflow orchestration → tool calling → single agent →
multi-agent
```

**Only increase complexity when evaluation shows a need.** Corollaries that came up
repeatedly: prompt before agent; single agent before multi-agent; workflow before
autonomous agent; deterministic routing before LLM routing; traditional search before
vector search where sufficient; RAG before fine-tuning for knowledge that changes.

In one case the honest answer was to *not* build the fashionable thing: exact structured
lookup over a single person's records solves the problem instantly and completely, so
embeddings would have added an API dependency and fuzzy chunk retrieval to a solved
problem. Saying "this is context engineering plus workflow orchestration, not RAG" cost
nothing and saved the first technical follow-up question.

---

## 3 — Making agents behave: structure beats instruction

The most transferable finding in this whole file.

> **A rule stated in a prompt is not a lever. Only a structure that makes the wrong
> move impossible is.**

The measurement behind it: adding an explicit "at most 4 turns" budget to an agent moved
its calls/turn from 0.95 to 1.00 and its turns/agent from **7.8 to 7.5**. Then the same
agents' *input layout* was fixed so the wrong move was structurally impossible, and
turns/agent went **10.5 → 7.6**.

### 3.1 Remove the capability instead of forbidding its use

Agent files said "do not read context files yourself" and "do not run additional
checks". Transcripts showed both instructions ignored, ~11 exploration turns per run:
`find`, `ls` across three directories, `git show`, `git log`, and reads of two source
files the agent had no business opening.

The cause was structural, not disobedience: **agents were given a filename pattern and
no path, so they hunted.** Two changes ended it:

- Dropping the shell tool from all three agents (they keep only read/write).
- Printing the inventory of valid inputs *into the briefing*, so nothing has to be
  looked up.

**Instructions are a request; tool grants are the actual policy.**

### 3.2 When agents behave stupidly, suspect the spec

**13 of 17 agents resolved the same relative path against the wrong root on their first
tool call**, got `File does not exist`, and went hunting — 47 of 71 extra turns in a run
were input-hunting, not analysis. The briefing handed out one bare-relative path next to
two rooted in a run directory; anchoring the third there was the *natural* reading.

Fixed by moving the files so the documented layout matched the filesystem. Verified:
18 of 18 first reads OK, turns/agent 10.5 → 7.6, cost per item $0.955 → $0.846.

**Thirteen of seventeen making the same "mistake" is a documentation defect with an
unambiguous majority, not a model problem.**

### 3.3 Do not hand an agent the thing you told it not to use

A grouping spec was 97 lines, much of it rationale written for a human. **An agent
reading rationale looks for confidence, and the nearest source of confidence is the
material it was told not to read:** in one run the agent opened the forbidden working
file **five times**.

Two fixes, both applied: move rationale out of the executable spec, and simply **do not
pass the path** of the thing it must not open.

> An instruction not to do something convenient loses to the convenience.

Generalised into a rule about context files: **rationale, incident records and worked
narratives live outside the runtime path** and are referenced by one line. The
executable spec carries one imperative line per rule — the decision, not its
justification.

### 3.4 Never inherit a model or a reasoning effort

A usage breakdown found **98 %** of spend in subagent-heavy sessions, **56 %** in
subagents typed `general-purpose` — and that week the *session* model was the premium
tier. The subagents were inheriting it.

Same trap in reasoning effort: a spawn without an explicit effort inherits whatever the
session happens to be set to, **so the same pipeline produces a shallow verification
pass on Tuesday and a deep one on Wednesday with no diff to explain it.**

Two rules:

- **The inheritance bug generalises; the tier choice does not.** *Never inherit* is an
  invariant. *Which* model is a per-spawn decision derived from the work.
- Stages that exist *only because an item is contested* pin high effort in the
  orchestration itself, because "contested" is unknowable at launch. A caller setting
  effort before any item exists sets a **floor, not a ceiling**.

### 3.5 Narrow agent types are worth more than they look

An agent definition granting only read/search/shell boots with ~24.6k of context, where
the default general-purpose agent boots with ~34.5k. That ~10k difference is **re-billed
on every turn of every agent** — and one 8-finding run had ~570 verification turns.

### 3.6 Turns are the cost, so batch independent calls

Measured: **1.00 calls per message over ~1,100 calls at 200k+ context.** Every message
replayed the full context to make one call.

The discipline that came out of it:

- Every **independent** call goes in ONE message.
- **A chain that depends on its own previous result is still one call** — feed it through
  a pipe, `xargs` or `$(…)` in the same shell invocation rather than taking a turn per
  step.
- Take a separate turn only when **your judgement** decides what to look at next — never
  for a step the shell could have computed.
- Read a region once. Never the same region twice, never in overlapping ranges, never
  re-read a file you just wrote.
- Never sweep a dependency directory recursively (39k files per app). Grep a known path.

### 3.7 An empty tool result is a tool failure, never evidence

One symbol-navigation tool returned `[]` for a language it did not support — measured
for types with **31 and 6** known implementors. A sweeper hit it, read `[]` as fact, and
abandoned symbol navigation for the rest of the run.

Related measurement from the same pass: a prompt rule mandating one collapsed shell
chain (which no structured tool call can join) produced **0 structured-tool calls in 426
turns; shell was 79.8 % of all calls.** A rule that makes the good tool unusable removes
the good tool.

### 3.8 Turn-level tracing makes read-discipline verifiable rather than merely assertable

The side benefit of measuring at turn level: the trace showed the search agent reading
two files it was **expressly forbidden** to read, in turns 3 and 4. No amount of
re-reading the prompt would have shown that.

### 3.9 Resuming a dead agent beats re-running it

One agent died on a mid-response connection error **one sentence before writing its
file** — all reasoning done, nothing on disk. Resumed from its own transcript with a
two-line "continue from there": it wrote the file and returned. A fresh spawn would have
cost ~$2.60 and ten minutes to rediscover what it already knew.

**Treat agent context as the asset, not the output.**

### 3.10 The minification incident

Context files are cost-multiplied, so they get minified. Then a minified mirror was
produced by **stripping stopwords — which deleted the word "No" from *"No resource
relies on the default allow-all"*, and left ~70 similar artifacts.**

Three rules out of it:

- Never strip a word that carries logic.
- Every compressed file gets a **mechanical** preservation check — extract every
  backticked span from the original and assert each still appears — never a re-read.
- The compressing agent runs at the reasoning floor, not a cheap tier: **a cheaper tier
  drops exactly the qualifiers ("only", "never", "unless") that carry the rule.**

The mirror itself was then retired: a *faithful* minified copy came out **larger than
its source**, so it bought nothing and left only a sync obligation.

**Compressing a context file is a refactor, and should be treated with a refactor's
verification.**

---

## 4 — Verifying LLM output: designing a review process with structural guarantees

Project B's verification protocol is the densest concentration of hard-won rules in any
of these projects. Every rule below is an incident.

### 4.1 Truth and significance are two questions, not one

Every verifier answers both, in this order, and an item survives only if both are yes:

1. **Is the claim true?** Does the cited code do what the finding says, at the cited
   lines?
2. **Does a consequence follow?** Name the user-observable, correctness, legal or
   divergence consequence.

**"Violates the standard" is not a consequence** — the standard exists to protect an
outcome; name the outcome. Passing (1) and failing (2) is a distinct verdict whose
reasoning must literally say *"true but not a defect"*.

The incident: two findings reported a pattern violation. Every verifier confirmed them —
correctly, the claim *was* true. The human rejected both as overengineering.

> **A mechanism-conformance claim always verifies as true, so only the significance
> question can kill it.**

That generalises well beyond code review: any LLM check of the form "does X follow rule
Y" will confirm itself. The useful question is always "and what breaks if it doesn't".

### 4.2 Cheap is safe only where it is structurally unable to decide

The cheapest stage's output schema has **no verdict field at all**. Not "the cheap agent
is told not to decide" — it structurally cannot, because there is nowhere to put a
verdict. A cheap agent that *could* answer `confirmed` would short-circuit the whole
item.

Same principle on the escalation branch: the only lever on the expensive consensus panel
is its **size** (odd, floored at 3), never its depth. **Uniformly shallower panelists err
the same way, and a majority vote cannot outvote a correlated error.**

### 4.3 A short-circuit verdict is worth 44 %

5 of 5 items came back `corrected` for drifted line references and an `18`→`20`
miscount — so the short-circuit never fired and every item bought a second expensive
opinion nobody disagreed with (~33 % of the run's verification cost).

Adding a `confirmed-with-edits` verdict — *every assertion stands; only field-level
presentation needed a mechanical edit, and the verifier supplies the replacement text* —
measured A/B: escalations 5/5 → 2/5, panels 1 → 0, **$45.80 → $25.86 (−44 %)**.

The boundary between it and a real correction is one test: **would a reader's decision
change because of this edit — whether to fix it, how urgently, or where?** A wrong line
number does not. A wrong root cause, a severity move, or a claim that turns out narrower
than written all do.

### 4.4 "Same resolution" means the same fix, not the same words

Byte-comparing free-text recommendations made two agents describing the *identical* fix
look like a disagreement. Consequence: **one 6-item run spawned 60 agents**, mostly
re-deciding three items that 17 verifiers already agreed on.

Fix: compare verdict *labels* plus token overlap, with one cheap adjudicator when the
overlap test is unsure — and open the expensive branch on "different" **and** on an
adjudicator that returns nothing usable. *An unanswered question is not an agreement.*

### 4.5 Park sub-claims, never whole items

A real defect (four bare untranslated exception throws) never became a ticket because a
*different* sub-question of the same finding was undecidable. Split the item: park the
undecidable sub-claim for human judgement, keep the sub-claims that are defects under
every reading.

### 4.6 One panel round only

Panelists receive identical prompts and no new information between rounds, so a second
round **can only re-roll the dice.** If no majority emerges, mark it disputed, list the
competing views *with their proposed replacement text* so a resolution can be applied
without excavating the run journal, and ask.

Also: **measure the majority bar against the configured panel size, never against how
many panelists survived**, so agents lost to an API error cannot silently lower the bar.

### 4.7 Independence is not negotiable

- Verify only in **fresh** subagents — never in the context that found, authored or
  documented the item.
- A context never reviews or completeness-checks its own output.
- Absence claims are **namespace-exact**: re-run every asserted search with a qualified
  pattern, never a bare basename. A bare name matching several fully-qualified names is
  itself a defect of the finding.
- Judge string-quality claims **string by string**, not action by action. One finding
  asserted a whole action showed raw text; 2 of its 4 paths were fine. **Never let the
  worst path's severity carry the paths that pass.**

### 4.8 Design the output format so scripts can own it

The finding format that made everything in §2.1 possible: **exactly 8 fields, in a fixed
order, and no other bullet permitted.**

| # | Field | Must contain |
|---|---|---|
| 1 | Problem | what fails, resulting state, mechanism |
| 2 | Why this is a problem | the real damage, not the symptom |
| 3 | Side effects | what else breaks; what a restore does **not** repair |
| 4 | Exact error message | verbatim, or `None — <why>` |
| 5 | Reproduction | a UI path **and** a developer one-liner |
| 6 | Affected code | path with line range |
| 7 | Urgency | one of four levels, followed by its justification |
| 8 | Provenance | the verification stage overwrites this with the verdict — **the finder never writes a verdict here** |

**The bar to aim for: a developer who has never seen the bug can understand it, reproduce
it and judge its priority without asking a single follow-up question.**

Four format decisions that each earned their keep:

- **A canonical, grep-able defect tag in the heading**, naming *what is wrong and where* —
  `[defect: no-confirmation-on-destructive-action @ <symbol>]`. Phrased identically across
  findings that share the defect, so they **collide on the same tag**: that collision *is*
  the grouping signal, and it lives in the heading so a grouping step never has to open a
  body.
- **The tag never names a remedy.** The developer decides how to solve it.
- **The whole file is an anchor contract.** Exactly one findings heading, and it must be the
  last top-level section; every item starts with a unique, stable id; anything that is not
  an item goes *above* the findings section. Five deterministic scripts address items by
  heading, so violating the layout makes them exit non-zero and refuse to write.
- **One item per distinct fix site.** The same defect at N call sites is N items, not one
  merged entry — the grouping pass recombines them into a single ticket with one fix line,
  so nothing is lost for the reader. Merging them earlier makes counts incomparable between
  runs (measured: the identical defect pair was written as 1 item in two runs and 2 in two
  others) and hides a per-site difference behind one location.

Two smaller ones worth copying: a **latent** item (not reachable in the running system)
carries a `Status — READ FIRST` field stating what masks it and what would un-mask it, plus
a marker in the heading; and something that is *correct behaviour with a UX complaint* stays
in the list, explicitly marked "(by design)", rather than being silently dropped.

### 4.9 Organise review output by severity, not by aspect

The per-aspect split (correctness, performance, architecture, database, tests, docs,
security) is a **work-splitting device, not the output shape.** One directory per severity,
one file per item, plus a summary. Consequences that fall out of that:

- **Subagents only *suggest* severity; the orchestrator assigns the final one**, normalising
  across aspects. **Severity reflects impact on correctness, compliance and merge-readiness
  — not which aspect happened to find it.**
- **Dedupe across aspects.** One underlying issue surfaces under several of them (a missing
  authorisation check is both "security" and "correctness") and must become one item.
- **Scale the review to the change.** Trivial change → one agent covering everything, or
  skip the review; small and focused → only that aspect; larger or cross-cutting → all
  relevant aspects in parallel. **State which aspects you are running and which you are
  skipping, with a one-line reason, before spawning anything.**
- **Do not check what CI already enforces.** Static analysis, style and test *results* are
  not part of a judgement review.
- **Scope items to the actual diff.** Do not flag pre-existing code in touched files.
- **An aspect description is a starting point, not an exhaustive checklist.** Each agent
  owns the full breadth of its aspect and reports anything material, including issues no
  example mentions.
- **A fresh completeness-check agent** verifies the aggregation — every item appears exactly
  once in the summary, per-severity counts match the files on disk, nothing was dropped or
  altered. The orchestrator must not check its own aggregation.
- **Clear the output directory first**, or ask. Never proceed with a previous run's leftovers
  in place.

### 4.10 Hand off *why*, not *what* — the context-dump pattern

The context that made a change is usually the most efficient place to address feedback,
because it holds the reasoning. But it grows too large to keep working in. So dump the
**non-obvious** knowledge into a file that fresh agents read:

> The diff already records *what* changed. This file's job is to record *why*, and anything
> a fixer would otherwise have to re-derive.

Sections that turned out to matter: key decisions **with the rejected alternatives and the
reason**; conventions a fixer must stay consistent with; **gotchas — things that look like
bugs but are intentional**, structural invariants deliberately not touched, anything
order-dependent or needing the live stack; and **known follow-ups, so a fixer does not
"fix" work that was intentionally deferred.**

Then one fresh subagent per item, primed with just that item plus this summary. And if you
cannot confidently tell whether an existing summary covers the same work, **ask before
overwriting** — do not append two incoherent halves.

### 4.11 Never rely exclusively on AI self-review

Stated plainly because it kept being re-learned: an AI code audit is worth nothing until
a deterministic check confirms what the model claimed. Generator ≠ verifier, wherever
that is affordable — in the audio pipeline (§7) one neural model generates and a
*different* one verifies, which is the same idea in another medium.

### 4.12 What actually makes an error message a defect

Worth writing down separately, because "the error message is bad" is the vaguest finding a
reviewer can produce, and an LLM will confirm it every time. A quoted string is only a
defect when it fails at least one of these:

- it does not name the real-world cause,
- it leaks an internal identifier (a UUID, a fully-qualified class name, an SQL state, a
  stack frame, a file path),
- or it offers nothing to act on and no code to report.

Three consequences that kept coming up:

- **A message that already states the real cause in plain language is correct behaviour**,
  no matter how it was assembled internally. "A sentence arriving as an exception message
  rather than through the translation layer" is plumbing, not a consequence.
- **Being untranslated is an internationalisation task, not an error.**
- **Technical detail belongs in the log, tied to a unique error code the user can quote.**
  That is what makes a plain-language message and a debuggable system compatible.

And two neighbouring rules from the same checklist, both about silent wrongness rather than
about wording:

- **A success message must describe what actually happened.** Never report success for work
  that was only queued — word it as "started", or surface the real outcome once it is known.
  And a failure path must not stay silent either.
- **A field bound to a name that exists nowhere silently loads and saves nothing.** No error,
  no message, no log line. Those are the defects worth hunting, because no user report will
  ever describe them accurately.

---

## 5 — Search, coverage and the classes of error nothing downstream can catch

### 5.1 Enumerate to find absences; trace to find defects

The same byte-identical audit task, run four times, returned **5 / 5 / 4 / 6 findings**.
That is not quality noise — the spread was systematic:

| Defect class | Found by |
|---|---|
| three *mechanism-level* defects (a helper dropping a permission, a shared component never asking for scope, two unscoped inputs) | **4/4 runs** |
| "this form has no owner selector **at all**" | **2/4** |
| wrong entity set for one operator role | 3/4 |
| one record saved under the wrong parent | 1/4 |

The trace explained it. The search agent traced the shared mechanism *well*. But it
listed the ~40 candidate surfaces once at turn 3 and **never walked the list** —
coverage was incidental to wherever the trace led.

> **The decisive asymmetry: a form that is missing the required element entirely has no
> code at its site to grep for.** It is reachable only by walking a list of expected
> surfaces and asking, per surface, "is it there?"

And the class it missed half the time was the *most severe* of the six — an active
failure, not a latent leak.

The rebuild: enumerate → bounded mechanism pass → N parallel sweepers → **coverage-
ledger gate** (any enumerated surface without exactly one disposition halts the run) →
**negative recall sample** → re-sweep if a `compliant` verdict is disproved.

**Why the negative sample exists:** verification only ever re-examines items that
*exist*. A wrong "this one is fine" is the one error class nothing downstream can catch,
so sampling those citations is the only thing that turns "did we find everything?" into
a number.

Cost supported the rebuild: detection was **$0.46 per finding** against **$1.43 to
verify one** — the expensive half scales with items *found*, not with search *effort*.
And the single searcher was the most wasteful agent of the run (42 turns, 26× replay),
so sharding bought coverage and cut replay at the same time.

### 5.2 Put the gate where the error class is unrecoverable

Everything downstream can catch a wrong item; **nothing downstream can catch a missing
one.** Named and left open rather than papered over: a fix site missing from the
worklist entirely is invisible to verification, grouping and generation alike —
permanently, and with no signal that it is missing.

### 5.3 Duplicates are the mirror image, and equally uncatchable

Two shards independently judge the same site because it was enumerated under two ids.
Verification is deliberately blind per item, the verdict cache reuses that blindness,
and assembly is count-conserving — **so nothing between enumeration and delivery ever
compares two items to each other.**

> **Both copies are individually true.** No verification tier, panel size or effort
> setting will ever remove one. A deterministic gate at enumeration is the only layer
> where it can be fixed.

### 5.4 Run the same input several times before trusting one result

A single run of a nondeterministic pipeline is an anecdote. And **normalise per item,
never per run** — runs return different item counts, so block totals are not comparable.

A ±1 of that four-run spread turned out to be pure accounting: the same two-call-site
defect was written as one item in two runs and two in the others. Settled by a
definition: **one item per distinct fix site.**

---

## 6 — Retrieval / RAG engineering

From project C (a hybrid retrieval platform with an evaluation harness) and project G
(a platform design study for legal-document search).

### 6.1 Make retrieval strategies comparable, not fixed

Four strategies selectable per request *and per evaluation run*, so "does reranking
actually help here" is answerable with numbers rather than opinion. Measured over 1,297
documents from two sources, 15 evaluation cases:

| strategy | recall@10 | MRR | nDCG@10 | abstention |
|---|---|---|---|---|
| keyword | 0.178 | 0.067 | 0.045 | 0.27 |
| vector | 0.304 | 0.149 | 0.120 | 1.00 |
| hybrid (RRF) | 0.327 | 0.165 | 0.139 | 1.00 |
| hybrid + rerank | **0.427** | **0.187** | **0.182** | **1.00** |

### 6.2 Fix the data before you trust any retrieval number

An earlier run of that table reported recall@10 **0.516**. It was inflated: **53 % of
the corpus shared a body with another document**, because the noise generator drew from
four sentences — so an expected document often had two chances to land in the top ten.
The corpus was fixed and the numbers *fell*. **They are lower and trustworthy rather
than higher and not.**

This is the concrete case for putting "fix the data" above "fix retrieval" and far above
"change the model" in an optimisation order.

### 6.3 Build the evaluation corpus adversarially, on purpose

Two layers:

1. **Ground truth**, deliberately split so that **no single document answers the
   question**: the commit made the change, the PR explains why (and records the
   dismissed review comment that turned out to be the cause), the ticket reports the
   symptom, a chat thread holds the hypothesis, the incident report holds the root
   cause, a CVE is a plausible red herring, a Q&A answer explains the framework
   behaviour, and the current source shows what actually runs.
2. **Noise** that looks relevant: other projects' docs on the same topic, other
   versions, exact duplicates, near-duplicates with drifted wording, superseded
   decision records, contradiction pairs, missing metadata, and documents of wildly
   different lengths.

Generation is **seeded**, so evaluation ground truth stays valid across runs.

Scoring covers both halves: retrieval (Recall@5/10/20, Precision@5, HitRate@10, MRR,
nDCG@10) and answers (evidence coverage, citation precision, required-property checks,
contradiction flagging, and **abstention correctness** — whether unanswerable questions
are actually refused).

### 6.4 Chunk per document type, behind a router

Markdown splits on heading structure and keeps the heading path; code splits on symbols;
conversations split on turn boundaries and **never mid-turn**; issues and PRs keep the
problem statement attached to its resolution; commits and vulnerability records stay
whole. The router is the seam for A/B-ing strategies later.

### 6.5 Evidence is weighted, not just matched

A type-authority table encodes that current source code is better evidence about present
behaviour than a two-year-old decision record, and freshness decays with an explicit
half-life. **This is what stops the semantically-closest-but-stale chunk from winning.**

### 6.6 Detect contradictions on claims, not documents

Narrow patterns extract `(scope, predicate, value)` triples; disagreeing values on the
same scoped subject produce a contradiction with a preferred source and a stated reason.
Claims about different projects never conflict, and `24 hours` vs `1440 minutes` is
normalised before comparison.

### 6.7 Citations are validated, not trusted

Markers the model invents are replaced with `[unverified]` and reported in the
uncertainty field. Confidence is zero without resolvable citations and drops with each
contradiction.

The cheap deterministic version of this, from project G, is the single best
hallucination killer available in a document-search product: **the quoted span must be
found verbatim in the source document, or the answer is rejected.** Cheap, deterministic,
and it kills most hallucinations without a model in the loop.

### 6.8 Idempotency is a design property, not an operational hope

Vector point IDs are `uuid5(namespace, "<chunk_id>:<embedding_version>")`. Documents
carry a content hash, so an unchanged record short-circuits *before* the expensive
embedding stage. **Re-running a full sync creates nothing.** Storing an
`extraction_version` alongside lets you re-extract after a prompt or model change
without re-running OCR.

### 6.9 One store is the system of record; the vector index is derivable

The relational store holds sources, checkpoints, raw records, documents, relationships,
chunks, jobs and evaluations. The vector DB holds vectors and is **rebuildable from the
system of record alone** — a reindex job re-chunks and re-embeds every active document.
So **only one backup must succeed**, and you take it first so a restored pair is never
newer in the index than in the record.

Keyword search sits behind an abstract retriever interface, so swapping the search index
touches one class. (Honest caveat kept in the docs: the relational full-text ranking
approximates but is not BM25.)

### 6.10 Measured operational limits worth knowing

- **CPU embedding is the ingest bottleneck**: ~0.4 s per ~200-word document with a small
  BGE model on a laptop-class CPU (~2.5 docs/s, so ~1.3k documents in ~9 minutes).
  **Batching across documents was measured and gains only ~15 %: the cost is the model,
  not call overhead.** Reaching a 250k–1M chunk target needs a GPU or a hosted embedding
  API — not a pipeline change.
- **Buffer vector writes per batch.** One upsert per document exhausted the vector
  store's file descriptors during a full sync (`Too many open files`) and made each
  write take seconds.
- Job claiming with `FOR UPDATE SKIP LOCKED` lets workers scale horizontally without ever
  processing the same job twice; large syncs resume from the last committed batch
  checkpoint rather than restarting the source.
- **Scale connector workers per source**, because rate limits differ per API.

### 6.11 Prove an abstraction by extending it, not by admiring it

The seam claim — "the remaining connectors plug in without redesigning the pipeline" — was
only worth anything once it was tested: **a second, entirely different source needed one
connector plus one normaliser and touched no chunking, embedding, indexing, retrieval or API
code.** That is the whole value of the measurement. An untested abstraction is a hope with a
directory structure.

Related discipline that made it possible: **build vertically, one source at a time.** Slice 1
ran end to end (connector → normalisation → relationship extraction → per-type chunking →
embeddings → vector index + full-text → hybrid retrieval → reranking → contradiction
analysis → cited answer with an uncertainty field) over a synthetic corpus, before a second
source existed.

And the honesty that goes with a slice: it is **one vertical slice, not production** — one
live connector, ~1,300 documents, 15 evaluation cases. A judged answer-quality scorer is
*wired but never scored*, and the README says so rather than listing it as a capability.
**"Adapter present" is not "measured".**

### 6.12 "Which documents do NOT contain X" is a filter, not a ranking

The single most useful modelling insight from project G. Absence questions need a
**set-based, exhaustive** answer — a negated filter plus a count — because the count *is*
the denominator for a coverage statement. A ranked search cannot tell you what is
missing.

Two traps around it:

- **With chunk-level indexing, the absence question must be answered at document level**,
  or almost every chunk matches "does not contain".
- **The filter is lexical, not semantic.** A differently-named or unlabelled clause does
  not match the search term, so the document is reported as missing something it
  actually has. The error direction is the tolerable one (over-reporting rather than
  missed risk), but **the noise is what decides whether the user trusts the tool.** The
  fix is an LLM verification pass **over the candidates the filter returned, never over
  the corpus** — plus a second pass prompted to find the thing *under a different name*.

### 6.13 Decide deliberately whether LLM cost sits at ingest or at query time

Pre-computing an inventory per document means re-reading every document whenever a new
rule appears. Discarding it moves the cost to query time, where **cost scales with
candidates per question rather than with corpus size** — fine as long as the filter is
selective, and something to watch with a break-even calculation (number of documents vs
number of sweeps). Mitigations: a cheap model for the mechanical pass, and **cache the
verdict per (document version, rule)** so a repeated sweep is nearly free.

### 6.14 Partly-wrong extracted text is worse than no text

A garbled document silently answers "does not contain". So: a quality flag per document,
`[illegible]` instead of a guess, and a visible *"N documents could not be read
reliably"* in the result set. Never silently treated as fact.

The most dangerous failure mode in a document pipeline, stated as a rule for a
transcription subagent: **forbid guessing, and do not give it cross-document context** —
an agent that has seen other contracts completes an illegible line with boilerplate from
a different one. *Do* give it task context (page, expected languages, "transcribe
verbatim").

### 6.15 Ground findings so the human does not re-read the document

Every finding needs the document, the page and the quoted span — **and a bounding box to
jump to.** Without the highlight the reviewer reads the whole document anyway and the
tool saved nothing.

### 6.16 Buy the plumbing; write the part that is specific to you

A platform decision worth copying: in project G's design, the managed search service buys
the indexer with change detection, chunking, embedding, hybrid ranking and permission
trimming; OCR is bought; infrastructure is declarative. **The LLM appears exactly three
times** — fixing OCR output, extracting a structured inventory, and verifying a
candidate. Never over the whole corpus.

Two things that must still be configured deliberately, because the default is silent
wrongness: **deletes must be explicitly detected**, or removed documents stay searchable;
and a **thin model gateway** so models can be swapped without touching business logic
(the model landscape moves faster than the code).

Deliberately not doing: fine-tuning, when the taxonomy changes faster than you could
retrain.

### 6.17 Recall over precision, when the asymmetry is real

For a risk-detection use case: a missed missing-clause is legal risk; a false positive
costs the reviewer 30 seconds. Name the asymmetry, then tune to it. And keep the
accept/reject decisions — **they are your evaluation data.**

### 6.18 Adoption is a product problem

Recorded because it is the part engineers skip: one saved playbook, one champion, one
measurable win, hours saved measured — then generalise. A trust ladder where v1 is a
filter that saves reading ("these 37 need your eyes, here is why, here is the page"),
never a decision-maker. **The domain owner owns the checks; if changing one needs an
engineer, adoption dies.** An explicit "what it cannot do" page, so the first bad result
does not kill credibility. And a success metric owned by the domain, not by IT.

---

## 7 — Evaluating a non-deterministic generative model (audio)

Project D: turning a text into an audiobook with offline TTS and verifying it with ASR.
No LLM in the run at all — Python plus two local neural models. The evaluation lessons
transfer directly to any generative pipeline.

### 7.1 Two verifications, neither replacing the other

| | compares | catches |
|---|---|---|
| **Text check** | prepared script vs. the original document | errors baked into the reference itself |
| **Doublecheck** | rendered audio vs. the canonical script | what the engine did to a correct text |

**A defect already in the script is invisible to the audio check**: the engine read
exactly what was written, so the comparison agrees. Do the text check first, and do it
before synthesising anything.

Four layers in the text check, in increasing independence:

1. A mechanical pattern check; a non-empty result is a blocker.
2. **An independent comparison working from the original document, not from your
   intermediate files.** A check that trusts your extraction cannot find a systematic
   error in your extraction. Hand the checker the list of *intended* transformations so
   it can tell them from real divergences.
3. A vocabulary diff against the source — the cheapest test for invented words. **Drive
   it to zero findings; then it is a gate, not a report you have to read.**
4. **Reconcile the word counts.** Explain the difference from the intended expansions
   alone. An unexplained deficit means content was lost; an unexplained surplus means
   something was invented or duplicated.

### 7.2 Measure what the check MISSES, not only what it reports

> A run with no findings can mean the chapter is clean or the check is blind, and until
> you have a number you cannot tell which.

So the blind spots are written down **as assertions of their current value**: then nobody
can change a threshold without seeing what it costs, and nobody can mistake the gap for
coverage.

### 7.3 Measure the sensitivity of the check by injecting faults

The concrete implementation of §7.2, and the best single idea in that project.

**Inject known errors into a copy of the reference text and count how many the finding logic
catches.** The *unmodified* text plays the role of "what was heard", so the measurement
needs **no faulty audio and no speech recognition at all** — it is exactly reproducible and
runs in seconds. It measures the sensitivity of the **logic**; how well the recogniser plays
along is a separate measurement against real audio.

Current state, kept as assertions:

| Injected fault | Caught |
|---|---|
| missing negation | 20/20 |
| transposed digits | 20/20 |
| four missing words | 12/12 |
| two swapped neighbouring words | 12/12 |
| **a single duplicated word** | **0/12** |
| **a single missing common word** | **0/12** |

**The two blind spots are recorded as expectations, not as bugs.** Both are discarded by a
three-token threshold, without which the recogniser produces constant false alarms. So the
file says, in effect: *whoever touches that threshold sees here exactly what they get for
it.* That is the difference between a known limitation and an unknown one.

Same idea applied to a known-unfixable residue: five paragraph boundaries cannot be merged
in either direction because both neighbours sit on a hard character limit. Recorded as a
**budget**. If the number is ever exceeded, a rule change created new splits — the budget is
the regression test.

And the fast regression grid around all of it: **~9,000 assertions in seconds, with no model
and no recognition involved, covering specifically the traps this project has already fallen
back into** — a silent truncation at 253 characters, hallucination-prone short units, a
rejected substitution, a thousands separator that destroyed decimals, heading detection.
A test suite as a register of past mistakes.

### 7.4 Build the cheap instrument, not the obvious one

Measuring sentence intonation looked like it needed the finished audio plus ASR word
alignment. Instead it reads the **per-unit render cache**, where every unit is stored after
all post-processing: the signal is the same as in the export bar an 18 ms crossfade, and
**the corresponding text is exactly known from the cache key rather than inferred.** That
removes both the drifting time axis and the ASR alignment step — which failed regularly on
this material anyway. Runtime ~100 s for six chapters, no model loaded.

**Where a pipeline already stores intermediate state, that state is usually a better
measurement surface than its final output.**

### 7.5 The wrong statistic will confidently give you a wrong answer

A slope fit over the last voiced segment made **29 % of declarative sentences "rise"** —
because that segment has a median length of 290 ms and is dominated by creaky voice. The
right measure was a robust **median excursion in semitones** between two defined windows,
with a 40 ms guard band excluding a plosive support and a trim margin.

Two parameter traps found the same afternoon, both silent:

- A pitch floor of 60 Hz instead of 100 Hz makes an octave-halving artefact **structurally
  possible** at a 190 Hz median. Constrain the estimator to the range the signal can
  actually occupy.
- Voicing must come from the library's **binary voiced flag, not its probability.** That
  probability has a median of 0.11–0.43 even in clearly voiced speech, so a 0.6 threshold on
  it **discarded 855 of 1,002 units** — and would have looked like a data problem.

And a classifier validated against hand marks was wrong twice: once from a verb list that
was too small (6 of 7 cases failed), once because the deciding grammatical form sits in the
**final** clause rather than at the start of the sentence.

### 7.6 Record a failing measurement as an expectation

Two of three intonation judgements currently **fail**, with the numbers attached. They sit in
the test suite as expectations, so **fixing one trips an assertion** and forces the baseline
and the expectation to be updated together. A failing property that is merely known drifts;
a failing property that is asserted cannot.

Related, and stated because it is easy to get wrong: one judgement was deliberately *not*
asserted, because the linguistically expected pattern does not hold in this language for
this sentence type. **Do not assert a property you only believe should exist.**

### 7.7 Deliberate cache invalidation, and the two things it breaks

Extending the cache key to include model identity and the four post-processing constants
**orphaned 717 existing entries — on purpose**, because otherwise a changed constant would
silently keep serving old audio. Two consequences worth planning for:

- **A baseline file measured before the change becomes a protocol, not a re-measurable
  quantity.** Say so in the file, rather than letting someone re-run a comparison against
  numbers whose inputs no longer exist.
- **A test that needs a reliable time axis now refuses to run** rather than appearing valid
  and attributing findings to the wrong units. The export file is unchanged; its cache is
  orphaned. A test that cannot establish its own ground truth should **fail loudly, not
  degrade quietly.**

That test is also pinned to a specific artifact by **fingerprint**, and aborts with an
explanation after a re-render — and the ground truth must then be re-established by hand,
**not copied from the automated report, which was misleading on exactly this question
twice.**

### 7.8 Document a broken tool instead of leaving it to be discovered

Two measurement scripts are listed in the README as **not runnable, with the exact reason**
(a variable used before assignment) and a pointer to the tool that replaced both. Cheaper
than a colleague debugging them, and honest about what is maintained.

### 7.9 Know your measurement noise before reading a result

The same text rendered twice varied between **4.13 s and 5.43 s** — wider than any effect
being compared. Repeat every measurement at least twice, and **when the spread swallows
the effect, say the measurement is inconclusive instead of reading a result out of it.**

The same rule saved project B from a false conclusion: identical prompts produce a 2.5×
turn spread, so anything smaller than that is not a result.

### 7.10 State a mechanism only after measuring it

*"The silence trim amputates the final plosive"* was plausible, coherent, and **wrong**:
the removed tail was pure silence at RMS 0.0000, identical at every threshold. Had the
fix been implemented on plausibility, the real cause would still be there.

### 7.11 Treat your instrument's biases as known, not as ground truth

ASR silently normalises a spoken "period" into a punctuation mark, and corrects
unfamiliar words towards known ones. **Read its output as evidence, not as truth.**

And where the measurement genuinely cannot answer the question, say so: a measurement
decides whether the engine *hesitates*; **a human ear decides whether the pronunciation
is right.** When a user reports something you cannot reproduce by measurement, treat
their ear as the better instrument and fix defensively.

### 7.12 The lexicon result: 103 → 3

A pronunciation lexicon built from sound orthographic reasoning had 103 entries. Tested
one by one, it **shrank to three.** It grew again only where a *measured* defect demanded
it.

The reason is architectural and worth knowing before writing a single entry: **the engine
has no phonemizer.** It reads character sequences and relies on what written text
normally looks like, so invented spellings it has never seen make things *worse*.
Respelling only helps engines that phonemize through a rule system. **Check which kind
you have first.**

**Keep the rejected candidates with their measurements in the file**, so nobody re-adds
them from the same plausible-sounding reasoning. (Same idea as a carry-forward ledger in
§8.3 — a rejection is information.)

### 7.13 Never split a sentence to speed up part of it

Autoregressive models plan one intonation contour per chunk, so a fragment is spoken more
slowly than the same words inside a full sentence, and every piece gets its own leading
and trailing silence. **Measured: splitting one sentence in three made it 32 % LONGER**
(20.4 s → 27.0 s; still 23.4 s after trimming the silences). Render the sentence whole
and post-process the span.

Also: do the chunking and set every pause yourself. Left alone the engine splits where it
likes and concatenates without defined pauses — that is what makes a render sound
breathless.

### 7.14 Positional mappings need an assertion, not a hope

**Assert that the number of assembled units equals the number planned.** The mapping from
text to signal is positional; an off-by-one attributes every later finding to the wrong
unit and is otherwise invisible.

### 7.15 Cache on everything that shapes the output, and re-do only the affected unit

The unit cache is keyed by the text **plus everything that shapes the signal** (model,
post-processing). That is what makes targeted repair affordable: re-render only the
affected units, never the whole chapter. And **report the hit rate of every automatic
intervention** rather than assuming it worked everywhere.

### 7.16 Run the check next to the work, not after it

Run the verification per chapter, inside the same process, right after the chapter is
written — the findings then arrive with the result instead of ten hours later, and both
models stay loaded. **Collect failures instead of aborting**; report chapter and reason
at the end.

And **read the engine's warnings while it runs.** A 253-character truncation announced
itself in the log; without that line the defect would have surfaced only after the full
run.

### 7.17 Sample before the long run, and quote the wall clock first

Render **one representative paragraph from the real text** — dense with the proper nouns,
jargon and numbers the material actually contains — not a demo sentence. Iterate on 2–3
sentence excerpts, never whole chapters. **Report the projected wall-clock time before
starting the full run**; nobody should discover a ten-hour render ten hours in.

### 7.18 Two signal-processing rules with the reason attached

- **Time-stretching: never a phase vocoder.** It destroys the phase relations between
  partials; the voice turns hollow and the artefact starts and stops exactly where you
  intervened. Use a time-domain method (WSOLA / `atempo`).
- **Do not fix a weak final plosive by editing punctuation.** Terminal punctuation buys
  both the falling cadence *and* the final consonant; removing it costs both.

### 7.19 Version drift in a dependency is a measurement problem

A base image bumped a major version of the audio toolchain, and the two-pass loudness
normalisation had been reworked in that release. **Render one chapter and measure it
against a chapter rendered earlier before starting a long run.**

---

## 8 — Loops, convergence and long-running autonomous work

### 8.1 What convergence looks like, over 18 runs

An audit-and-fix loop, auditing its own tooling, fixing what it found and committing each
run separately. Scope **pinned to the previous run's commit** — without that the file set
changes between runs and the finding count stops comparing at all.

| Run | Findings | Fixes carried from previous run |
|---|---|---|
| 3 | 99 | 3 |
| 4 | 62 | 3 |
| 5 | 52 | 8 |
| 6 | 45 | 2 |
| 7 | 17 | 2 |
| 8 | **22** | 2 |
| 9 | 18 | 3 (0 regressions) |
| 10 | 11 | 3 (2 regressions) |
| 11–16 | 14, 32, 13, 12, 5, 1 | — |
| 17 | **0** | the loop exits |
| 18 | 34 | a fresh re-entry on a wider scope |

Through run 10: **374 findings fixed across 10 commits; the test suite grew from 0 to 46
tests.**

### 8.2 What the loop taught that a single audit could not

- **Convergence is real but not monotone.** 99 → 62 → 52 → 45 → 17, then **22**. A rising
  count under a pinned scope means the audit went *deeper*, not that the fixes broke
  something — and the metric that tells those apart is "findings in files the previous
  run never swept". Without it you do not have a convergence signal, you have a number.
- **Zero is not the end.** Run 17 returned zero and exited; run 18 re-entered on a wider
  scope and found 34. **A zero is a statement about the pinned scope, not about the
  code.**
- **The exit condition needs a boredom clause** — not just "zero findings" but "two
  consecutive runs yield only low-severity documentation drift". Otherwise the loop
  spends real money polishing prose.
- **Tests, not fixes, are what makes the count fall.** The suite's coverage is handed to
  the audit agent as **ground truth**: a finding claiming an invariant that a passing test
  covers is *refuted*, not reported. Tracked as its own metric — "candidates the suite
  refuted".

### 8.3 A carry-forward ledger has three lists, not one

**Known-fixed** (re-report only if wrong or regressed) · **known-deferred (report these —
they are unfixed, not settled)** · **settled** (never report again; a row leaves only when
a human reverses it).

**Without the middle list, a deliberate deferral is indistinguishable from an oversight
on the next run.**

### 8.4 Derive loop state from the commit log; never store it

Run number and pinned scope are derived from git precisely so they cannot go stale — and
**the newest run directory is not a safe source**, because an aborted run leaves a
directory with a partial sweep in it.

**One run = one audit + one fix phase + one commit.** A run without a commit breaks the
derivation for every run after it. And never on a timer: a second run started before the
first commits derives the same number and the same scope.

### 8.5 Fix one item at a time, and validate by re-running what found it

The fix loop, stated generically: process items strictly sequentially; one fresh subagent
per item, scoped to exactly that item — no unrelated refactoring, no fixing other items
on the way; mark it done the moment its fix is reported; respect an explicit loop limit
and report what remains.

**A fix is validated by re-running whatever found the item — never by a mechanism of its
own.** Items found by an executable check → re-run the check. Items found by judgement →
re-run the originating search, or re-verify the touched items.

---

## 9 — Concurrency, failure and how agents actually die

### 9.1 69 agent deaths across 9 archived runs. Without exception: HTTP 429.

Not crashes, not tool errors, not schema errors — **our own usage limit** (50× session
limit, 19× weekly). Signature: a zero-row transcript, a synthetic model name, 0 turns,
$0.

- **Deaths arrive simultaneously**, in 1–3 minute windows (19 deaths in one run inside
  three minutes) — not a gradual degradation you could detect early.
- **One limit event hits several runs.** On one occasion agents died in **four
  concurrently running workflows** at the same minute. A pipeline's namespace isolation
  applies to *files*; **the usage budget is global and shared.**

### 9.2 A dead agent silently changes your denominator

In one run two stages covered 14 and 3 items respectively. Block sums stop being
comparable. So dead agents are **counted and marked, never omitted**, or the agent count
is simply wrong — and everything is normalised per item.

**The asymmetry that decides retry policy:** a dead verifier is repeated. A dead **search
agent is not** — it is the only point of detection, so its failure is a different kind of
event.

### 9.3 An uncomfortable cost interaction

Those failure paths are exclusively 429s under concurrency. So **a $0.04 agent dying
triggers a ~$2.55 expensive fallback panel — precisely when several runs are in flight
and it is least affordable.**

### 9.4 Concurrency rules for agent runs that cannot see each other

Runs are asynchronous and mutually invisible; nothing serialises them. Safety is
therefore entirely a matter of every run writing only inside its own namespace:

- **Never hardcode or re-derive a path.** The natural guess (`<topic-slug>Tests.txt`) is
  exactly the file a parallel run of the same topic already owns.
- **Never delete by wildcard.** An `rm -rf *.slices` typed in good faith at cleanup time
  destroys a concurrent run's artifacts — and **the victim run cannot detect it; it just
  starts producing wrong output.**
- **Shared files are append-only.** A read-modify-write of a shared list silently drops
  whatever a concurrent run appended in between; `>>` cannot lose an entry.
- **Namespace containment beats collision defence.** "The folder is inside the run
  directory, which belongs to this run alone" makes the collision *impossible* instead of
  unlikely — and leaves no second, weaker mechanism to keep in sync.

### 9.5 Two agent sessions in one repository will clobber each other

Real incident: a concurrent session emptied a run's output directories mid-measurement
and dropped in a file nothing in the first session had written. Nothing was under version
control at the time; **git would have made it a non-event.**

Recovery held the more interesting lesson. The sources were rebuilt by replaying the
subagent transcripts. The first attempt replayed only `Write` calls and produced a
**2-page** document — because the agent had written it long and then **trimmed it with 7
`Edit` calls**. Replaying `Write` *and* `Edit` in order restored it exactly.

> **A transcript is a replayable log, but only if you replay every mutation, in order.**
> Write-only recovery produces a plausible, wrong artifact rather than an obvious failure.

The measurement itself survived because it came from transcripts, not from files:
**derive metrics from an append-only source, not from mutable output.**

### 9.6 Fail loud, and make sure "loud" means what you think

Every deterministic script validates its preconditions before writing and exits non-zero,
leaving the file untouched. But a *formatting* detail was load-bearing: a conservation
guard counted headings matching a pattern, so a missing id prefix on a title read as a
**lost item** (`in=5 out=4`) and a stray one read as an **invented item**
(`in=4 out=5`).

**Both fail loud with a count error that reads like data loss but is a title typo.**
Agents responded the way anyone would — tweak and re-run; one 5-item run spent 3 of 14
tool calls re-running the assembler. The script now owns the prefix (idempotent), so a
fail-loud exit means a **real** structural problem.

Applied to a document renderer, the same principle: fail loudly on an ambiguous selector
(naming all three matches), on a selector matching nothing (listing the allowed set), and
on selecting the same item twice — and print a NOTE when a selection would silently drop
an entry, because the failure is invisible in the PDF and expensive downstream.

---

## 10 — Observability: instrument the instrument

### 10.1 Your cost tracker needs testing like any other code

Testing a transcript-to-tracing exporter against a real pipeline run found three bugs:

1. **All subagent data was invisible.** Subagent transcripts live in a subdirectory, not
   the project root the tool globbed, and the "is sidechain" flag is always false in the
   main transcript. For this pipeline that meant missing **84 % of wall clock** and most
   tokens.
2. **Every duration exported as zero.** Generations were emitted with
   `start_time == end_time`, so the whole pipeline rendered as instantaneous — useless
   for finding slow steps, which is the main reason to have traces.
3. **The cheap model was priced at frontier rates.** Model ids carry decorations the price
   list lacks (date suffixes, context-window markers), so exact-string matching dropped
   them onto `default` — a **5× cost overstatement.**

A cost tracker that silently omits 84 % of the workload and reports every duration as
zero **looks perfectly healthy until you check it against a run you already understand.**

### 10.2 The expensive bug in an observability tool is attribution, not arithmetic

A cost report attributed each API call to the turn that invoked it and reported the last
pipeline run as **1 call, $0.13**. The real run was **51 calls, $3.94** — a **30×
undercount that looked plausible enough to ship.**

Cause: **a slash command's work does not live in the turn that invoked it.** The command
turn only spawns the skill (46 output tokens). The human then supplies input in a *new*
turn, and every finished background agent comes back as its own turn — 6 turns, 4
subagent transcripts, one logical run.

Fix: assemble runs **causally.** A turn joins the open run if it back-references a
tool-use id the run spawned (always causal) or spawns an agent itself within 30 minutes.
Turns sandwiched between the command and the last caused turn come along; anything after
it does not — so the follow-up question two minutes later ("what did that cost?", $4.19
on its own) is correctly excluded.

> **The token maths was right the whole time. What was wrong was *which rows belong to the
> thing you named*** — and that error is invisible unless you check a total you can
> predict independently.

### 10.3 Two numbers disagreeing by 2× is a parsing question, not a rounding one

An earlier report was a **~2× overcount** because it summed usage-bearing transcript
*lines* instead of billed *responses*. Streaming emits 2–3 lines per response sharing one
message id and one request id, each repeating the same cache figures. 102 lines, 51
responses. **Check the unit before the maths.**

And a third framing error, found only by being challenged: the "run" being reported was
one of **three** runs that went into that deliverable ($2.83 + $0.40 abandoned + $3.94 =
$7.17). **"Are you sure?" is worth a re-derivation, not a defence** — the challenge and
the original answer both turned out half-right.

### 10.4 Validate a measurement method against ground truth

Transcript-derived phase spans were only trustworthy because they matched the harness-
reported durations **exactly** (134 / 678 / 1628 / 2442 s).

And label what a number is: **time in a transcript is derived, not recorded.** There is no
latency field; "time" is the gap ending at a response, which is *model* time only — it
excludes tool execution and human think time. Label it, or people will read it as wall
clock. **Prefer undercounting to overcounting when you must guess** — then show the wall
span next to it so the gap is visible.

### 10.5 Your measurement tool will need its own debugging

An agent-metrics script classified pipeline steps by prompt text, and its pattern for one
stage also matched briefings that merely *cited* that stage's output. **Every verification
agent was absorbed into the wrong row; the table showed 18 agents of a stage where one had
run.** Classification now keys off the structural agent type wherever one definition serves
exactly one stage, and a test fails the build if a classification pattern matches nothing.

### 10.6 Trace spans, and degrade to structured logs

A retrieval pipeline emits spans for analysis, retrieval, expansion, reranking, freshness,
contradiction analysis, generation and citation validation. **Without tracing credentials
the same spans are emitted as structured JSON logs**, so a bad answer is always traceable
to the evidence it saw. Observability that requires a running service is observability you
will lose at the worst moment.

### 10.7 Self-hosting a tracing stack: four traps

1. **A container database's `POSTGRES_PASSWORD` is only honoured on first init.** The
   compose project reused an existing volume, so a freshly generated password never
   matched. Every "authentication failed" against a container database that used to work
   is this, and no amount of re-reading your connection string will show it.
2. **A password test that proves nothing.** `psql -U postgres` from inside the container
   succeeded while the app kept failing: local socket connections use `trust` in that
   image, so the password is never checked. **Verify credentials over the same transport
   the application uses**, or the test is theatre.
3. **Installed ≠ configured ≠ active.** A plugin reported "already installed" from an
   earlier attempt and then *"5 config options not yet set"* — so it had been sitting there
   tracing nothing. The config flag is only read *during* install and a second install is a
   no-op; the fix was uninstall + reinstall.
4. **The same stack twice on one machine.** A second instance was already running in
   another project, plus an orphaned third volume set. Two database containers on one data
   volume would corrupt it. **Check the mounts before starting anything** — and most of
   these tools are multi-tenant by design: one instance, one *project* per context, not
   one stack per repo.

**And the placement lesson:** 57 lines of that config were nearly committed into an
application repo "for reproducibility". Then they were read: ports, secrets,
container-internal URLs, a telemetry switch. **Not one line referenced the project**, and
the plugin traces every session on the machine regardless of directory. So it is machine
setup, not project code. **Ask what a file is *about* before you ask where it should live.**

---

## 11 — Generating documents: templates, patches and deterministic verification

Project A and E, but the shape applies to any "LLM writes a deliverable" system.

### 11.1 Give the deterministic layer the whole mechanical job

One entry point owns merging, template filling, page-fit escalation, PDF rendering, text
hygiene, **file naming** and verification. No prompt and no standards document may spell
out an output filename — they ask the script (`--print-paths`). The verification step is
not decorative: the run fails if the page count is wrong, if the text is not selectable,
if a forbidden dash survived, if a required address block is missing, or if a private
contact address leaked into a document that should carry the public one.

Measured: the whole deterministic phase — template fill, page-fit ladder, headless-browser
render, 12 verification checks — runs in **1.67 s**. A single office-suite HTML conversion
is 0.89 s; a browser print is 0.55 s.

**That first measurement ended the search for a slow script.** There was nothing to
optimise in Python, and the entire question was turn count and context size.

**Measure the deterministic part first, if only to eliminate it.**

### 11.2 An unset check must not be able to pass for a clean run

The leak check reads its comparison value from an environment variable and reports
**SKIP, not OK**, when that is unset. A green run with two skipped checks is a different
statement from a green run.

### 11.3 A declarative patch format needs a defined operation order — and it will bite you

The renderer applies `rewrite` before `select`. So if a `rewrite` renames a category and a
`select` in the same patch references the **old** name, the render aborts with "selector
matched nothing".

That exact bug happened **three times across three runs**, and was noted as a candidate
fix twice before being fixed. The rule: **a `rewrite` must never touch the field a `select`
in the same patch selects on** — keep the prefix, change the substance; or select by index;
or resolve selectors against the base before rewrites apply.

> A learning without a fix is just bookkeeping.

### 11.4 Print the valid selectors instead of hoping the model knows them

One generation pass invented three of three selectors — titles it *wanted* to exist. Cost:
a 61k-token repair round trip, more than the fix. The renderer refusing rather than
guessing was correct; the cheap fix is not a better prompt but **printing the selectable
titles next to the base path.**

Confirmed from the other direction: the run that invented nothing was the one whose
upstream phase had **named the evidence items explicitly** instead of describing them by
category. **A selector the generator has seen spelled out is one it copies; a category is
one it fills in.**

### 11.5 Never let a prompt depend on a disposable artifact

A generation phase's structure reference pointed at a previous run's file in the
build-output directory. Routine cleanup deleted it, and the phase was pointing at a
missing file — while also being told "if a path is missing, stop".

**A pipeline input stored in an output directory is a time bomb.** Inputs live with the
templates and examples, where nothing sweeps them. Bonus: storing the tone example in the
exact format the phase must emit makes **one file both the tone reference and the schema.**

### 11.6 Track a generated file when a stale copy is dangerous

Context digests are build artifacts and were gitignored on the usual reasoning. Reverted,
with the better argument: **tracking them makes a stale one show up in `git diff` instead
of silently shipping outdated facts**, and a fresh clone works with no build step.

(A footnote on how that revert happened: the original decision was written down, with its
reasoning, in the very file being edited — and the edit appended without reading up. Read
the file you are changing.)

### 11.7 Scoping estimated from bytes is not scoping

A prediction that the phase-scoped context digests held ~9k tokens of droppable fat
delivered **~1.8k.** Auditing every key against what each phase provably reads:

- Two key sets that looked *obviously* droppable held exactly the projects a
  frontend-leaning or quantitative brief would match — and the file's own comments already
  recorded someone making that exact mistake once.
- One key the exclusion comment had claimed to drop since v1 was **never actually
  dropped** by the code. *Comment-code drift: a comment describing behaviour nothing
  executes.* **Comments rot faster than code, because nothing runs them.**
- The bullets that looked most droppable were the evidence the matching phase matches
  against.

> **A fact base that is mostly evidence does not compress by scoping, because every phase
> cites evidence.** The estimate came from *file sizes* — which measure bytes, not need.

Two of three "phase-scoped" digests were also **byte-identical** (same md5), so a
documented "~39 % cheaper" figure had been measured against something else entirely.

### 11.8 Guardrails for a generated context digest

- Verify sub-keys, not just top-level keys.
- Assert that the honesty/exclusion rules survive into **every** phase.
- Assert digest values are a **verbatim subset** of the source: pruning may remove, never
  reword.
- **Delete obsolete phase digests on rebuild**, so a prompt that was not updated cannot
  inject a stale file that still looks current.

### 11.9 List only what is legal as an input

A pipeline listed every JSON in a directory as a candidate base document — including the
tailored outputs of *previous* runs. One directory listing away from building a new
deliverable on top of an unrelated one. The script now lists role bases only.

### 11.10 Inline the asset; do not reference it

A signature image is inlined as a base64 data URI rather than referenced by relative path,
because the document is rendered from a scratch copy that a fitting loop writes, rewrites
and deletes. **Any relative `src` is one moved file away from a silently missing image in
a PDF nobody re-opens.** ~30 KB, and it cannot break. Composite onto the page's own
background colour rather than relying on transparency, so nothing can render a halo.

### 11.11 A background-removal problem that was a colour problem

Cutting a pen signature off a photographed page: it crosses a printed rule and a printed
label, so **no rectangle isolates it and luminance alone keeps all three.** What separates
them is hue — paper photographs warm, printer toner stays warm even when dark, and the
ballpoint ink is the only thing where blue meets or beats red. Gate on `B − R > −3`, then
take darkness against the paper level as the alpha, and the rule and label disappear on
their own. **Two lines of arithmetic where a hand-drawn mask would have taken far longer
and aged worse.**

Four follow-on findings worth keeping, because each is a general trap:

- **A uniformly-wide stroke reads instantly as a graphic, not a pen.** Binarising plus
  morphology makes the topology right and the width constant. The fix was to keep both
  images: the cleaned binary mask decides *where* ink is, the greyscale decides *how much.*
  Multiplying them brings back pressure variation and stroke taper without the dirt.
- **Count connected components; do not look.** Several strokes were torn where the
  signature crossed the printed line — the hue filter removed the line *and* the ink lying
  exactly on it, about fifteen pixels per crossing. Invisible at 12 mm display size,
  obvious in print. Seven components where the real pen lifts give five. Repair only the
  paired stroke ends across the line, using the local stroke width, and only where ink
  genuinely continues on both sides. **A genuine 46 px gap stays open — making an image
  cleaner than the original is no longer cleaning.**
- **Some edges cannot be rescued and must be replaced.** Every filter pass on the mask
  keeps working on an outline made of paper fibres and camera noise. The way out was to
  abandon the outline: thin the mask to a one-pixel centreline (Zhang-Suen), smooth *that*,
  and redraw it with a round nib. The edges are then **drawn rather than photographed**,
  and mathematically smooth, while the letterforms survive.
- **Two things that looked wrong first.** Taking nib width per-pixel from the distance
  transform reproduces the paper grain as a string of beads — a ballpoint has *one* width,
  so the measurement belongs heavily smoothed and capped. And the mask is measurably wider
  than the real stroke (here nearly 2×) from closing, bridging and the photo's blur halo;
  without that correction, tight loops fill in. Finally, thinning invents a branch at every
  bulge, the curve fragments, and every fragment end gets a taper that reads as a broken
  stroke — so fragments are stitched where exactly two run smoothly into one point, and
  tapering is applied only where the centreline really ends. The script asserts at the end
  that **zero centreline pixels were left unclaimed by a path.**

### 11.12 Deleting output from a repository

~40 MB of generated documents left git in one commit (697 deletions). They rebuild in
1.67 s from the source JSON plus a template. **If you can regenerate it, it is output, not
knowledge.** A knowledge base stores facts and generators, never their output.

---

## 12 — Grounding, honesty and factual discipline in generated text

This came from a document-generation pipeline where a false statement has a real cost, but
every rule here is a grounding rule that applies to any RAG or generation system.

### 12.1 Honesty bugs do not live in the facts; they live in the step that summarises them

The fact store said: a community project, 2009–present, with a specific framework's
modernisation. The generator rendered that as "multi-year professional experience". **The
data was right and the inference was wrong.**

Deleting the sentence from the output would have regenerated it on the next run. The only
fix that survives is **a note in the fact base that forbids the inference.**

### 12.2 The output can be a faithful quote of your own bad rule

A self-characterising sentence was rejected from a generated document. It turned out to be
a **direct quote from the project's own style guide**, listed under "authentic phrasing
patterns". The model did not hallucinate the voice — it obeyed the documentation of it.

> Fixing the artifact without fixing the guide just schedules the sentence for next week.

Follow-up, an hour later, and the more interesting half: the *pattern* was fine; what
failed was its translation into another language, which dropped a four-word qualifier and
thereby inverted the meaning. **The first fix banned the whole pattern; the real rule was
narrower and language-specific.** Overcorrecting a style rule costs a genuinely good
sentence in every future document.

### 12.3 A gap table with forbidden phrasings survives prompt injection; "be honest" does not

Where a brief emitted gaps as **binding table rows with explicit banned strings** —
never "built a package", never "architected the platform" — both downstream generators
respected them across two prompt hops, and reported them back unprompted with grep
verification.

**Say what NOT to write.** The guards that worked were phrased as banned strings, not as
principles.

### 12.4 Correct at every site the claim appears, not only where you noticed it

A claim was corrected in one place and left standing, uncommented, in a second structure
that a generator also reads. Any future run could legitimately re-introduce it. **A
correction must land at every place the claim exists.**

And it was marked `DO NOT USE` rather than deleted — deleting it would have hidden a
divergence from a source document that someone might compare against.

### 12.5 Ask when the answer is not derivable, and only then

Two human round-trips in one run were both worth it: one answer became a sentence, the
other deleted a line, and neither was derivable from the data. Elsewhere: one blocking
question ("mention this or not?") replaced a coin flip that would have wasted a whole
document.

The complement is a rule against asking: **never ask for what you can already answer.**
Language, register, slugs and output paths are always derived, never asked.

### 12.6 "We did X" is not a fact base until you know what X means technically

"Integrated external systems" could mean vector embeddings or plain tool integration —
two completely different claims. **One clarifying question prevented a false claim in
every future document.** The answer went into the fact base as an *integration*, explicitly
not as embeddings, so it is usable for one kind of question and unusable for the other.

Same shape, twice, on the same day: were graph-drawing tools evidence of "graph
technologies"? No — those draw diagrams; the thing being asked about is a queryable
structure with traversal. Both wrong answers would have been *plausible on paper* and both
die in the first technical follow-up.

### 12.7 Not lying is not the same as confessing

A generator volunteered a gap in a document as an honesty move. **Omitting is allowed;
denying and asserting are not.** The never-lie rule requires that nothing false is claimed
— it does not require actively raising every gap. There is a right place for a
"currently learning" line, and it is not the middle of an argument.

### 12.8 A supporting document is an upper bound on what you *could* claim, not a measure of what you *should*

A third-party reference document credited a person with work they had done only two to five
times, in a "do a few so you understand it" sense. **The conservative version wins against the
document**, and the discrepancy is recorded as a scope limit rather than silently
inherited.

Corollary from the same review: that document named **not a single technology and not a
single number.** So it evidences *responsibilities* and nothing quantitative — and a blanket
note claiming it "extends" the role was wrong and is now explicitly bounded.

### 12.9 Overstatement almost never arrives as an invented fact

It arrives as **a stronger verb for a real one.** A claim to have *built* a real-time sync
mechanism was wrong: the mechanism existed and was *extended*. Recorded as a hard rule —
**extending an existing system is never building it** — plus a matching lock in the fact
base.

Two sibling patterns from the same week:

- **Silent domain transfer.** Experience in one regulated, money-critical domain does not
  make you experienced in a different regulated domain. What transfers is the *working
  method* ("data must be legally correct"); the domain claim does not.
- **Silent role transfer.** Doing the *components* of a role (requirements work with
  customers, presentations, project leadership) is not the role. Name the components; do
  not rebrand them.

**And the rule against upgrading verbs is not a ratchet that only turns one way.** One
downgraded verb was restored a week later — with the evidence — once the actual story
turned out to support the stronger word. An assistant that only ever talks you down is as
useless as one that talks you up.

### 12.10 A number needs an example, and a derived number needs a label

- **"~50 API resources" means nothing until one of them is named.** A count without an
  example is a number the reader cannot picture.
- A count of test classes and cases-per-class may be stated; **their product may not**, if
  nobody ever ran the count. A true-looking unverified multiplication is the same as false.
- **A derived figure is labelled as derived** in the artifact itself. Never let arithmetic
  read as a measurement.
- **A self-ranking with a number on it ("top 3 of a 7-person team") reads like a fact and
  is an opinion.** In public, the reader gets to ask "measured how?" and you never get to
  answer.

### 12.11 One true detail can still be the wrong detail

A genuine fact about how some of the work was done was a *governance* flag to the audience
rather than evidence of initiative. Same substance available without it; recorded as a
hard never-write rule. Truth is a necessary condition for including something, not a
sufficient one.

### 12.12 Structure and sequencing, not new sentences, fix most of it

- **The last line is what people remember.** A summary that ended on the one thing not yet
  learned inverted the whole document. Moved inward; ended on the strongest evidence. Same
  sentences, same honesty, different last impression.
- **You cannot close a gap by opening with it.** Where a required years-figure genuinely
  isn't met, state the depth, never the number, and place it *after* the evidence.
- **An honest document is a subtraction problem.** One artifact was dropped entirely rather
  than let it sit next to a claim it could not support.
- **Deleting an apology is free.** Removing "(not completed)" from an education entry left
  the same facts, the same years and the same honesty — the parenthesis was doing nothing
  except apologising.
- **Volunteer the strongest caveat before anyone asks.** A bounded claim makes the
  unbounded ones credible. And caveats are **content, not footnotes** — same type size, in
  the section they belong to, never shrunk or collapsed.

### 12.13 Match the artifact to what the audience actually asked for

- A brief that says "no degrees required, show us artifacts" is not lowering a bar — it is
  **moving it somewhere you cannot bluff.** The public repository had to carry the whole
  argument.
- Where an audience writes "impact, not job titles", applying under the more senior-sounding
  frame is a reading-comprehension failure, not ambition. **Pick the frame that matches how
  they work, not the one that ranks highest.**
- Where a brief asks for infrastructure competence, listing the three real things (container
  stacks, a CI system, Linux) beats implying a hyperscaler. **Infrastructure competence is
  not a vendor logo, and a gap you name costs less than a claim you cannot defend.**
- The best argument is often the one the brief never asked for. For a payments audience,
  fiscal-correctness and event-sourcing work said more about whether the systems would
  survive contact with their domain than another paragraph on prompts would.
- With a mixed-language brief, **mirror the party that demonstrably wrote the copy**, not
  the reposter.

### 12.14 Making generated prose not read as generated

A separate problem from factuality, and one with a surprisingly mechanical answer. The
governing observation: **a single AI tell is survivable; an accumulation of predictable
patterns discredits the text.** So the ruleset is mostly a blacklist plus a variance
requirement.

**Vary the things a model holds constant.** Sentence length, paragraph length, rhythm,
structure — and above all **sentence openings** and punctuation. Repeated openings and a
uniform paragraph length are the tell that survives every other edit.

**The blacklists, kept literal so they are checkable rather than aspirational:**

- *Buzzwords:* delve, underscore, pivotal, transformative, seamless, robust, leverage,
  unlock, empower, elevate, navigate, tapestry, landscape.
- *Stock phrases:* "It's important to note", "At its core", "In conclusion", "Overall",
  "Here's why", "But here's the thing", "The result?".
- *Structural tells:* hedging on every statement ("generally", "typically", "tends to"),
  manufactured suspense, unjustified hype (revolutionary, groundbreaking, game-changing),
  overused em dashes, rhetorical questions, rule-of-three lists, one-line paragraphs
  throughout, generic openers ("In today's fast-paced world…"), and a formulaic conclusion
  that summarises what was just said.
- *Wrong-format tells:* bullets, frameworks and checklists where prose works better — and
  repeating the prompt back.

**Two rules that matter more than the blacklists:**

- **Preserve the author's certainty level.** "I think" stays tentative; "I noticed" never
  becomes "this proves"; one experience never becomes a universal rule. **Never make someone
  sound more authoritative or more senior than their evidence carries.** This is the voice
  equivalent of §12.9's verb rule.
- **A rework changes voice, never facts.** Every number, name, price, duration and technical
  detail carries over unchanged; nothing is rounded, softened or re-derived. Where a fact has
  to go, it goes whole. **Treat any changed figure in a rewrite as a bug** — the same
  content-drift argument as §2.1 and §13.15, applied to prose.

And the constraint on the editing pass itself: **never "improve" a text by making it less
funny, less personal or less recognisable.** Polish goes first; the voice never. The final
test is one question — *does this read as one identifiable human author, or as a generic
assistant?*

---

## 13 — Presentations and visual output as an engineering problem

Project E: generating a technical presentation as a single dark HTML page. Surprisingly
rule-dense, and the rules generalise to any LLM-generated visual artifact.

### 13.1 Split structure from style, or you will never restyle anything

Three layers: **structure** (layout, navigation, behaviour — identical in every deck),
**styles** (one file per named look), **elements/figures** (the building blocks and the
figure archetypes).

**The rule that makes the split work: structure and elements never name a colour, a font
or a pixel value that carries taste.** They refer to *role tokens*. A style file is the
only place those roles get values. Swap the style file and the same deck becomes a
different product; the markup does not change. If a style needs to edit structure, **a
role token is missing** — add it there rather than hard-coding a value.

Sizes work the same way: structure defines *relations* (the head is the largest text, one
step in a chain equals every other); a style defines the numbers.

### 13.2 Two accents with two jobs, and it is structural

`--accent-structure` draws connectors, arrows, rails, borders, progress.
`--accent-meaning` carries the section tag, the takeaway, the number the slide exists for.
Semantic colours (ok / bad / warn) are used **only to mean something**, never to decorate.

The best single instance of this: in a stage diagram, **the stages that call a model get
one colour and every deterministic stage gets another.** That one convention carries a
whole architectural argument without a sentence.

### 13.3 A word budget is the only thing that forces a cut

**Measured: a first 14-section build came to 2,687 words against a reference design of
roughly 300.** Every rule that adds text does so *per section*, and on a scrolling page
nothing forces a cut.

So: ~40 words of prose per section, hard. Eyebrow, headline, one-line lede, nothing else.
Figure labels and legends do not count; bullets, technology strips and caveat paragraphs
do. **Count before delivering.** Everything over budget goes into the speaker notes — that
is what they are for. **A section that needs more words needs a better figure.**

### 13.4 Replace text with graphics, and be specific about which graphic

- Sequences over time → a **timeline with a real axis**, not a period column.
- Before/after numbers → **bars on a shared scale**, not two figures side by side.
- Architecture → a flow diagram that distinguishes components, external systems, data
  stores, and **which stages call a model versus which are deterministic code.**
- Search spaces, funnels, reductions → **a shape that shows the reduction.**
- A table is the fallback, not the default.

And author diagrams as **inline SVG in the page's own tokens** — never a pre-rendered
image, which cannot follow the theme and whose labels cannot be kept inside their boxes.

### 13.5 A figure is the argument, drawn — and there is a method for it

The most reusable thing to come out of the presentation work. A figure is not an
illustration of a sentence; it **is** the argument.

1. Write the claim as one sentence.
2. **Name its shape.** If you cannot, the section has no figure yet — and usually no claim.
3. Draw the shape from a small primitive kit, **unlabelled.** It should already be readable.
4. Add the fewest labels that remove ambiguity.
5. Add the legend.
6. Place the one number.
7. **Delete anything left that answers no question.**

The primitive kit is deliberately tiny — rounded rectangle, 1px stroke, dot, bar, ring, arc,
arrow, dashed ghost, cone, glow. **A deck reusing ten shapes reads as one system; a deck with
thirty reads as clip art.**

Claim → archetype, as a starting kit rather than a closed list:

| The claim | Shape |
|---|---|
| Many candidates, few survive | funnel |
| Something changed | before / after |
| One thing fails in many ways | hub and modes |
| Independent paths agree | converging paths |
| It grows without bound | growth curve |
| **Something is missing** | **absence grid** |
| Complexity collapsed | tangle to node |
| Two tests, in order | gate sequence |
| Input becomes output | transform pipeline |
| It developed over time | timeline |

Rules that apply to every figure:

- **One variable per figure.** Two variables mean two figures.
- **Colour encodes kind, never mood**, and the same meaning keeps the same colour throughout.
- The number the figure exists to deliver goes **inside** the figure at display size.
  **More than three numbers means it is a table.**
- Nothing inside a figure falls below the style's label floor. **If it does, the figure holds
  too much — split it rather than shrink it.**
- **Build labels that must wrap as HTML, not as SVG text.** SVG text does not wrap and will
  collide at some other width. (Same reason legends are built from HTML components rather
  than text inside the SVG.)

**Drawing absence deserves its own note, because it is the hardest one and often the most
valuable** — and it is the exact visual counterpart of §5.1, where absence was also the
hardest thing to *search* for. **Give it a positive form:** a dashed outline where a filled
one should be, an empty slot in an otherwise complete grid, a ghost bar beside a measured
one. **Never rely on a reader noticing that something is not there.**

**And no metaphor figures.** No lightbulbs for ideas, no brains for models, no rockets for
launches, no gears for process. **Draw the mechanism, not a picture of the concept.**

### 13.6 Every visually distinct mark gets a legend entry

Each colour, each opacity variant, dashed reference lines, direction arrows, tint depth.
Build the legend from the page's own components, never as text inside the SVG. **A legend
entry identifies; it does not argue** — two or three words.

And **label a figure with what it is**: a shape-of-the-problem diagram says so, and is not
passed off as measured throughput.

### 13.7 Compute legibility at the width it actually renders at

A diagram fitted into a narrower column scales its type down with it. Either lay the
diagram out to fit the column (vertical, or two rows) or raise its source font sizes.

### 13.8 Nothing escapes its box, and the cause is the layout

The failure is almost always layout, not content: **grid and flex items default to
`min-width: auto`, so one wide string grows its track and the `overflow-x: auto` never
fires.**

- `min-width: 0` on every grid/flex child that can hold wide content.
- `overflow-x: auto` + `max-width: 100%` on the wide element itself, in its own scroll
  container.
- `overflow-wrap: anywhere` on anything that can hold a long path, identifier or chip.
- `minmax(0, …)` in grid track definitions, never `auto`.
- `overflow: hidden` on SVGs so no label spills past its frame.
- **Verify at a narrow width before delivering.**

### 13.9 Declare every token in base `:root`

**A colour defined only inside a media query or an attribute block is the classic
unreadable-page bug.** If a page commits to one theme, commit: paint the background and
every colour explicitly, and skip the toggle nobody asked for.

A dark PDF export that *preserves* the theme rather than inverting it needs its own block:
exact colour adjustment, fixed background layers hidden, `break-inside: avoid` on panels
and figures, and `min-width` dropped from wide SVGs — **an `overflow-x: auto` figure is
clipped when printed, not scrolled.**

### 13.10 Everything meant to be read is visible at rest

**Never park content at `opacity: 0` waiting on an observer.** Entrance animation is CSS
with `animation-fill-mode: both`, so a throttled frame loop can never leave a section
invisible. Reserve `requestAnimationFrame` for counters and generative graphics, and let
`prefers-reduced-motion` jump them to their final state.

Related, from the deep-link side: **re-apply a hash jump after webfonts load**, or the link
lands off target.

### 13.11 Do not build state you then have to explain

The decision that removed the most complexity: one continuous page, everything on it. **No
slide state, no click-to-reveal, no prev/next.** If a detail is worth keeping it is worth
showing; if it is not, cut it or move it to the notes.

And when a feature is removed, **remove its UI with it** — no dead toggle, no orphan
shortcut, no footer sentence describing a feature that is gone.

### 13.12 Headings state their subject; numbers are the argument

- **A heading states its subject.** The reader knows what a section holds before reading a
  word. *"Automated evaluation of a non-deterministic TTS model"* is a heading.
  *"Closed Loops"* is a mood, and *"85 candidates, 3 accepted"* is a riddle whose answer is
  the section.
- Directly under it, **a one-line strip of the tasks, technologies and techniques** that
  project actually used — the audience's own words, comma-separated, no verb — so a skimming
  reader gets the stack before the prose. Never padded with something the project did not
  use.
- **Numbers go in a big-number or stat slot, never inside a sentence.** `99 → 0`, `26×`,
  `−44 %`, `~99k vs ~0 tokens`.
- **Titles as two-word noun phrases naming the mechanism** — never a sentence, never a
  question. The kicker is one short declarative sentence. The foot carries the one-sentence
  takeaway.
- **Cards hold a heading and at most one line of prose. No bullet lists of prose.** Where a
  list is unavoidable it becomes rows with a key and a status pill.
- **A slide without its takeaway sentence is unfinished** — that is a completeness criterion,
  not a style preference. The pre-delivery checklist is worth having in this literal form:
  every slide has a takeaway and a section tag; every distinct mark has a legend entry; no
  figure label below the floor; the emphasis glow used once per slide; **the meaning-accent
  colour appears only where something is being claimed**; every navigation key and deep link
  works; print shows everything; reduced motion stills everything.

### 13.13 A case study without trade-offs reads as a demo

Every case study carries measured results **and** what the design cost. And include one
**"what I would do differently"** beat: it is the strongest seniority signal available and
costs nothing.

Every section should answer one of three questions — *what was built, how does the author
think, what changed because of the work* — and anything answering none of them gets removed.

### 13.14 A whole reference deck with no images at all

The headline finding when a reference deck was reverse-engineered: **it contains no
images.** Every visual is hand-written inline SVG or a CSS card composition. No photos, no
stock illustration, no icon fonts, no logo walls. Fully reproducible with no asset
supplied.

Its other structural choices, all worth stealing: fixed 1280×720 slides scaled to the
viewport with one `transform` (so one authored composition renders anywhere); an overview
grid whose thumbnails are the **real slides scaled**, never screenshots; a print stylesheet
that shows every slide and hides the chrome; **depth from a border and a soft glow, never a
drop shadow or a lighter fill.**

The scaling trade, stated honestly: **type gets smaller on a small screen rather than
reflowing.** That is the right failure for a presentation and the wrong one for a document
— which is why the smallest label size is a *floor*, chosen so it survives being scaled
down.

### 13.15 Editing a published page: script it, do not retype it

**Edit by exact-string or regex pass, verified by diff, with `<style>` and `<script>` held
out of any global substitution.** Retyping a page through a model rewords what nobody asked
to change — the same content-drift argument as §2.1.

And on publishing: **freeze before sharing outward.** Republishing reaches every holder of
the link immediately, with no announcement. Send a dated frozen copy and keep editing the
working one; never leave two live URLs whose titles do not say which is which.

---

## 14 — Repository, data and git hygiene around AI work

### 14.1 Duplication is a latent bug, and the drift is the defect

**Three of five pipeline defects found in one test session were two copies of one rule that
had grown apart.** A documented workflow contradicting the code; two filename conventions
in one run; a hygiene rule enforced on one of two paths (and the unenforced one shipped 12
forbidden dashes into a PDF).

The rule that came out of it: **every rule lives in exactly one file — the most general one
in which it is still true.** A rule true for every channel goes in the general file; a rule
belongs in a specific file **only if it is false for the others**; specific files
*reference* the general rule instead of restating it. When a new source document repeats a
universal rule, add the source reference only.

And **a reference is a pure pointer**: it must never explain, summarise or restate the
referenced file's content. Referenced content changes, which makes the explanation silently
wrong. Name the reference's *purpose*, never its mechanics. This holds even when restating
feels helpful for reliability — a subagent that reads the file gets the authoritative rule;
**a paraphrase in a prompt only creates a second copy that drifts.**

Deleting a duplicate is a real deliverable: one 170-line script became a 60-line wrapper
**by owning nothing** — all parsing, pricing and SQL stayed in the one module that already
did it.

### 14.2 Let one artifact be the definition of the thing

Three instances of the same trick, all of which removed a file that could drift:

- **A tool's docstring *is* the schema.** The function that fills a template documents the
  content JSON's structure, and nothing else does. There is no second schema document to fall
  out of date.
- **An index-only README.** "Every rule, command and convention is documented at exactly one
  place; here you only find out *where* that place is." A README that explains rules becomes
  a second, drifting copy of them — the exact defect of §14.1.
- **One example file is both the tone reference and the schema**, because it is stored in the
  exact format the generating phase must emit.

### 14.3 Placement follows cost, not tidiness

Text in an always-loaded instruction file is re-billed on **every turn of every agent**
(~740 frontier-model turns in one audit run). Text in an on-demand file is paid once by the
one agent that reads it. So: needed by every agent → the always-loaded file. Needed only
for job X → the file the agent doing X already reads. The always-loaded file keeps at most
a one-line pointer.

### 14.4 Untracking is not removing, and a history rewrite is not surgical

Two incidents, one afternoon:

- **`git rm --cached` plus a `.gitignore` entry leaves the file in every previous commit**
  — and leaves its *contents* inside unrelated files' history, where the same private
  strings had been quoted in a log, a fact base and agent docs. Purging needs both path
  filters **and** text replacement.
- **A history rewrite hard-resets the working tree and takes untracked, gitignored files
  with it.** Untracking 17 private files left them safely on disk; the rewrite half an hour
  later deleted every one. They came back from a backup bundle, which is the only reason
  this is a footnote and not an incident. **Take a bundle *and* a copy of the files before
  rewriting.**

### 14.5 Enforce a privacy convention by naming, not by memory

Per-application artifacts stay out of git **by the naming convention itself**
(`offer_<company>_*`, `patch_<company>_*` are gitignored), so a new one is untracked the
moment it is generated rather than by anyone remembering. And in the public log, everything
is pseudonymised **consistently** — a stable letter per recipient — so a run can still be
followed end to end while the identities stay out entirely.

Two things kept out of a public repo for reasons worth stating: a scanned signature (it
does not make a document legally binding, but it is trivially pasted under anything by
whoever holds the file — and the build fails with instructions when it is missing, rather
than quietly shipping an unsigned document); and a private contact address, because
**writing it down to check for it would publish exactly the string that needs protecting**
— hence §11.2's environment variable and its SKIP.

### 14.6 What gets committed and what does not

Committed on purpose, even though it is generated: the **context digests**, because a stale
one is dangerous (§11.6). Not committed: **generated PDFs and documents** (reproducible in
~1.7 s, so they are output, not knowledge) and the virtualenvs.

And after a long run, **copy the output somewhere safe before any cleanup** — the
gitignored directories are exactly what `git clean -fdx` deletes. List them first
(`git clean -ndx`).

### 14.7 Pin your linter's rule set explicitly

An unpinned linter went from reporting nothing to **51 findings across the same files**, on
the same code. Now the rule list is enumerated in the project config, with every ignore
carrying a comment saying why, and CI runs the same commands as the local check so a green
local run and a green pipeline mean the same thing.

Notes from doing this twice:

- Formatter set to **preserve quote style** — letting it rewrite quotes buries real diffs.
- **Dead-code detection needs a confidence threshold tuned to the framework.** Below ~70 %
  it flags every framework-called route handler and schema field as dead. Two genuine
  findings at 60 % were acted on (one helper deleted, one unused setting wired up).
- **A low security finding is annotated, not suppressed** — a seeded PRNG in a corpus
  generator, where reproducibility is the whole point.
- **Four suppressions in one codebase, each carrying its reason.** A `noqa` without a reason
  is just a hidden bug. (Three of them say *this table is the definition of the dash rule,
  so it must contain the dashes it forbids.*)
- **A dependency with an unfixed advisory gets quarantined into its own optional extra**,
  never installed by CI, never in the image, never on the serving path — and the gate is
  left strict rather than given an ignore list, so the exposure stays visible.

### 14.8 Coverage, honestly

**38 %, and stated as honest rather than flattering:** the tests cover the pure logic where
a refactor can silently change behaviour — patch merge and every one of its failure modes,
text hygiene, timespan splitting, item dropping, date formatting, the asset guard. The
uncovered remainder is the subprocess and CLI layer, verified end to end by the renderer's
own checks. One test builds a real document from the actual template, so that path is
exercised against the real artifact rather than a mock.

For the retrieval project, the equivalent discipline: unit tests force a hash embedder and
a mock LLM so they never depend on a model download or a paid API — and **the four tests
that assert genuinely *semantic* retrieval quality skip under the hash embedder rather than
pretend to measure it.**

### 14.9 Migrations, health and readiness

Small things that are always the same and always forgotten:

- CI runs a **`downgrade base && upgrade head` round-trip**, so an irreversible migration
  fails the build.
- **Liveness never touches a dependency; readiness does** and returns 503 so a load balancer
  removes the instance.
- **Secrets are never in a database row.** The row holds the *name* of the secret and
  non-secret options only.

### 14.10 Cut the ends of the pipeline off on purpose, and say why

Both ends of the document pipeline are absent by decision, not as stubs:

- **Finding the inputs.** An earlier version scraped five job boards — it worked, and it was
  **removed rather than kept**: none of those boards has a usable public API, so all of it
  was scraping (against two of their terms of service, and broken by any redesign).
  **Carrying a component whose failure mode is "a source silently returns 0 hits" is not
  worth it** for a system whose value is the generation step. Recoverable from git history
  if a legitimate API appears.
- **Sending the output.** Every submission endpoint needs the recipient's credentials, so
  the pipeline ends at a finished, verified PDF and sending stays manual.

Stating the reason is what makes it a decision rather than a gap.

---

## 15 — Working method: the parts that turned out to matter

Distilled, because these are the ones that changed outcomes repeatedly.

**On measuring**

- **Measure before optimising, then re-measure.** The first diagnosis is often plausible and
  wrong; a single timing on the actual command settles it in seconds and can redirect an
  entire investigation.
- **Measure the deterministic part first, if only to eliminate it.** One 1.67 s number ended
  the search for a slow script.
- **A number without a mechanism is a story.** "41 min → 1.16 s" is true and useless until
  you can say which of the three changes did the work.
- **Know your noise floor before reading a result**, and say "inconclusive" when the spread
  swallows the effect.
- **A/B one change at a time**, and normalise per unit of work, not per run.
- **Estimate from what a consumer provably reads, not from file size.** Bytes measure
  storage, not need.
- **Measuring a proxy you chose because it was easy will flatter the change.**
- **Derive the break-even on paper before running the experiment.**
- **Measure the sensitivity of your checks by injecting known faults**, and record the blind
  spots as assertions of their current value.
- **Prove an abstraction by extending it.** An untested seam is a hope with a directory
  structure.

**On building with models**

- **Prefer deterministic code for deterministic tasks**; use the model where ambiguity,
  language, semantics or judgement genuinely live.
- **Structure over instruction.** A rule in a prompt is a request; a tool grant, a schema
  without a verdict field, or a path you simply do not pass is a policy.
- **Give models only the context they need**, and restrict tools by least privilege.
- **Use structured outputs and validate them** — a selector matching nothing or matching
  twice fails the run, loudly, naming the alternatives.
- **Never inherit a model or an effort.**
- **Independent verification**: generator ≠ verifier where affordable; verification via
  rules first, a second model next, a human where risk warrants it.
- **Create a baseline before optimising, and document it** — including in a tool's own
  docstring, next to the code it justifies.
- **Turn real failures into evaluation cases**, and keep the rejected candidates with their
  measurements so nobody re-adds them from the same plausible reasoning.
- **Autonomy grows with demonstrated reliability**, in stages: read-only → recommend →
  draft → execute with approval → execute low-risk automatically.

**On the human in the loop**

- **Ask the blocking question, and only the blocking one.**
- **"Are you sure?" is worth a re-derivation, not a defence.**
- **When agents behave stupidly, suspect the spec.**
- **A human correction should become a permanent rule, not an edit.** Fixing the artifact
  without fixing the rule schedules the same defect for next week.
- **Report actual outcomes.** If a step failed, say which and why; if a check was skipped,
  say skipped, not passed.
- **Do not claim what you cannot perceive.** In an audio pipeline: measure what is
  measurable, hand the human files to judge the rest, and treat their ear as the better
  instrument.

---

## 16 — Open problems, honestly labelled

Kept because a known-unclosed risk is more useful than a tidy list.

- **A fix site missing from the worklist entirely is invisible to every later stage** —
  permanently, and with no signal that it is missing. Enumeration is the single point of
  detection.
- **Duplicate items cannot be caught downstream at all** (§5.3). The candidate gates are
  written down with their costs, and one of them would break the count-conservation
  invariant everything else relies on. Recorded as an open decision, not a fix.
- **An expensive escalation branch has no post-fix measurement.** Across 13 later runs: 138
  items validated, 30 tie-breaks, **0 panels**. So its cost is $0 in practice — but it is
  *unreached, not unreachable*, and two of the four paths that still lead to it are
  infrastructure failures rather than genuine disagreements. Its unit price today can only
  be **modelled** (~$2.55), so it is labelled an estimate and kept out of every measured
  table. **A real figure cannot be forced**: no flag induces a genuine verdict
  disagreement, and provoking one by weakening a side would measure a configuration that is
  not the shipped one.
- **A retrieval evaluation set of 15 authored cases is a smoke test, not an evaluation.**
  Named as such, with the eventual target (200–500) written down.
- **Free-text absence questions cannot be answered with a guarantee.** "Does not contain X"
  is only bounded once the wording or the rule is defined. And a document is often a family
  (a master agreement plus amendments), so absence may need precedence rules. Recorded as
  open questions rather than solved problems.
- **Two text-normalisation traps in the audio pipeline are documented and unguarded.**
  Expanding an abbreviation must not leave its trailing period behind mid-sentence (it tore
  a sentence in half), and de-hyphenation across line breaks destroys real hyphens (it
  merged a genuine compound into one word). Rejoin only where the source had no hyphen of
  its own.
- **The whole body of work has one structural gap, and it is worth naming: none of it has
  been exercised in production.** These systems run privately, so the disciplines that only
  exist under real traffic are untested — gradual deployment, monitoring production
  behaviour, feedback loops from real usage, prompt-level adversarial testing and
  retrieval-specific red teaming (corpus poisoning), and success metrics defined as an
  upfront contract rather than ad hoc per experiment. The neighbouring gap is classical ML:
  datasets, labelling, fine-tuning and training custom models never came up, because
  LLM-integration and retrieval work never required them.
- **Some things stay unbuilt on purpose**, and that is a decision to state rather than a
  gap to hide: no vector store where exact structured lookup solves the problem completely;
  no fine-tuning where the taxonomy changes faster than a retrain cycle; no scraping
  component whose failure mode is silence.
