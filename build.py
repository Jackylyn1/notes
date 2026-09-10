#!/usr/bin/env python3
"""Build the static site: one HTML page per Markdown source in content/.

Deliberately small. It exists because every published finding needs a STABLE
deep-link anchor — a LinkedIn post points at one finding, not at a 21k-word page.

The anchor rule that drives the custom slugifier below: heading text in the
sources carries section numbering ("1.1 Cost is quadratic in turns"). Slugifying
that verbatim yields "11-cost-is-quadratic-in-turns", which BREAKS every
published link the moment a section is renumbered. So the numbering is stripped
before slugifying: the anchor is derived from the words only.

Run:  ./.venv/bin/python build.py
Out:  docs/ (served by GitHub Pages: Settings -> Pages -> main /docs)
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import markdown

ROOT = Path(__file__).parent
CONTENT = ROOT / "content"
OUT_DIR = ROOT / "docs"
ASSETS = ROOT / "assets"

SITE_TITLE = "Engineering notes"
SITE_TAGLINE = "Measured findings from building with LLMs, agents and retrieval."


@dataclass(frozen=True)
class Page:
    source: str  # filename in content/
    out: str  # path within docs/
    title: str  # <title> and og:title; the visible <h1> comes from the Markdown
    description: str  # meta description and og:description


PAGES: tuple[Page, ...] = (
    Page(
        source="learnings.md",
        out="index.html",
        title="Engineering notes — agents, retrieval, evaluation",
        description=(
            "Measured findings from two months of building LLM pipelines: what an agent "
            "run actually costs, why structure beats instruction, and the error classes "
            "nothing downstream can catch."
        ),
    ),
)

# Leading section numbering to strip before slugifying, e.g. "1.1 ", "12 — ", "3.4.5 ".
_NUMBER_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)*\s*(?:[—–\-.:)]\s*)?")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str, separator: str = "-") -> str:
    """Stable, readable anchor derived from the heading's WORDS only.

    Numbering is stripped first so renumbering a section cannot break a
    published link. Markdown inline syntax is stripped so `code` and *emphasis*
    in a heading do not leak into the anchor.
    """
    text = _NUMBER_PREFIX.sub("", text)
    text = re.sub(r"[`*_]", "", text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return _NON_SLUG.sub(separator, text).strip(separator)


def render_markdown(text: str) -> tuple[str, str]:
    """Return (body_html, toc_html)."""
    md = markdown.Markdown(
        extensions=["toc", "tables", "fenced_code", "attr_list", "sane_lists", "footnotes"],
        extension_configs={
            "toc": {
                "toc_depth": "2-2",  # top-level sections only; the page is long enough
                "permalink": "#",
                "permalink_title": "Link to this section",
                "slugify": lambda value, sep: slugify(value, sep),
            },
            "footnotes": {"BACKLINK_TEXT": "return"},
        },
        output_format="html",
    )
    body = md.convert(text)
    return body, md.toc


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="color-scheme" content="dark">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="article">
<link rel="stylesheet" href="{root}assets/site.css">
</head>
<body>
<a class="skip" href="#content">Skip to content</a>

<header class="masthead">
  <div class="wrap">
    <a class="wordmark" href="{root}index.html">{site_title}</a>
    <p class="tagline">{site_tagline}</p>
  </div>
</header>

<div class="wrap layout">
  <nav class="toc" aria-label="Contents">
    <h2 class="toc-head">Contents</h2>
    {toc}
  </nav>

  <main id="content" class="prose">
{body}
  </main>
</div>

<footer class="footer">
  <div class="wrap">
    <p>Prose licensed <a href="https://creativecommons.org/licenses/by/4.0/">CC&nbsp;BY&nbsp;4.0</a>,
       code samples MIT. Corrections welcome — the numbers matter more than being right first.</p>
  </div>
</footer>
</body>
</html>
"""


def build() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    shutil.copytree(ASSETS, OUT_DIR / "assets")

    for page in PAGES:
        src = CONTENT / page.source
        if not src.exists():
            raise SystemExit(f"missing source: {src}")
        text = src.read_text(encoding="utf-8")
        body, toc = render_markdown(text)
        depth = page.out.count("/")
        html = TEMPLATE.format(
            title=page.title,
            description=page.description,
            site_title=SITE_TITLE,
            site_tagline=SITE_TAGLINE,
            toc=toc,
            body=body,
            root="../" * depth,
        )
        out = OUT_DIR / page.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        anchors = len(re.findall(r'id="[^"]+"', body))
        print(f"built {page.out}  ({len(html):,} bytes, {anchors} anchors)")

    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print("built docs/.nojekyll")


if __name__ == "__main__":
    build()
