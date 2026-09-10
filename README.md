# Engineering notes

Measured findings from building with LLMs, agents and retrieval — published so a
finding can be linked to instead of retyped.

**Live:** https://jackylyn1.github.io/notes/ *(after enabling Pages, see below)*

This repository exists for one reason: **every finding needs a stable, public,
deep-linkable address.** A post that summarises a finding spends it; a post that
links to one invests it.

## Layout

| Path | What it is |
|---|---|
| `content/*.md` | The sources. Markdown, one file per page. |
| `assets/site.css` | The dark reading theme. Every token declared in the base `:root`. |
| `build.py` | Markdown → HTML. ~140 lines, one job. |
| `docs/` | **Generated.** What GitHub Pages serves. Committed on purpose — see below. |

## Build

```bash
python3 -m venv .venv && ./.venv/bin/pip install markdown
./.venv/bin/python build.py     # writes docs/
```

Local preview:

```bash
cd docs && python3 -m http.server 8765   # → http://localhost:8765
```

## Why `docs/` is committed

A generated file belongs in git when a stale copy is dangerous, and for a
website it is: a stale build serves outdated content silently. Committing it
means staleness shows up in `git diff` instead, and Pages needs no build step or
Action. When this grows past ~8 pages, move to a generator with a deploy
workflow — not before.

## The anchor rule

Headings in the sources carry section numbering (`1.1 Cost is quadratic in
turns`). Slugifying that verbatim gives `11-cost-is-quadratic-in-turns`, which
**breaks every published link the moment a section is renumbered.**

So `build.py` strips the numbering before slugifying: the anchor is derived from
the words only, giving `#cost-is-quadratic-in-turns-not-linear-in-tokens`.

Two invariants the build enforces by construction, and which must stay true:

- **No duplicate anchors.** A duplicate makes a deep link ambiguous.
- **No `_1`-suffixed anchors.** Those are auto-deduplicated and therefore
  unstable; if one appears, two headings collided and one needs renaming.

Check both after any edit:

```bash
grep -oE 'id="[^"]+"' docs/index.html | sort | uniq -d      # must be empty
grep -oE 'id="[^"]*_[0-9]+"' docs/index.html                # must be empty
```

## The gate

```bash
./check.sh     # rebuilds, then verifies; non-zero exit means do not publish
```

Sixteen checks, including both anchor invariants below and the anonymisation
guard. It is a gate, not a report to read: drive it to zero findings.

## Before every publish

The notes are written to carry no employer, client or internal-system names.
That property is not self-maintaining — re-check it on every change:

```bash
grep -niE 'gastro|gpos|riverty|wpt|naruto|EKIP|kassensich|dsfinv|filament|serena|gitlab|RAGTask|career-kb|profile\.json|Company [A-Z]' docs/*.html content/*.md
# must return nothing
```

## Enabling Pages (once)

Settings → Pages → Build and deployment → Source: **Deploy from a branch**,
Branch: **main**, Folder: **/docs** → Save.

A custom domain later is one `CNAME` file in `docs/` plus a DNS record; no other
change is needed.

## Honesty rules for the content

- Numbers are measured unless labelled as estimated.
- Where a figure was later found wrong, both the wrong number and the correction
  stay — the correction is usually the more useful half.
- Turn counts, token counts and timings are exact. Dollar figures rest on
  estimated model rates and are labelled as such; prefer ratios.

## Licence

Prose and figures: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Code: MIT. See [`LICENSE`](LICENSE).
