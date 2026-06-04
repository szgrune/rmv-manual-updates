"""
Provider-agnostic LLM layer for change analysis.

Strategy: send FULL CHAPTER TEXTS to the LLM. This allows it to read both editions
completely before making judgments, avoiding false positives from section-level
extraction artifacts (split sections, noise headings, etc.).

Select backend via ANALYZER_BACKEND env var:
  claude  — Anthropic claude-opus-4-8 (default, prototype)
  openai  — OpenAI gpt-4o (org handoff)
  local   — Token-free difflib fallback (no API)
"""

import json
import os
import re
import time
from abc import ABC, abstractmethod


SYSTEM_PROMPT = """\
You are a rigorous analyst comparing editions of the Massachusetts Driver's Manual.
Your job is to identify ONLY genuine legal or regulatory changes between editions.

ABSOLUTE RULES — violating these produces incorrect output:
1. Content that appears in BOTH editions — even if reworded, split across paragraphs,
   or moved to a different position — is NOT a change. Do not flag it.
2. Section or topic reorganization (same content, different order or chapter) is NOT a change.
3. Only flag: new laws/requirements not in the older edition, updated fines or penalties,
   new permitted or prohibited behaviors, newly added topics, or clearly removed topics.
4. When reporting a change, bullets MUST be DIRECT VERBATIM QUOTES from the 2026 text.
   Copy the text word for word. Do not paraphrase. Wrap the quote in double quotes and
   follow it with a parenthetical citation: "exact quote" (2026 Massachusetts Driver's Manual).
5. For removed content (exists in old, absent from 2026), quote from the older edition and
   cite it the same way: "exact quote" ([year] Massachusetts Driver's Manual).
6. Be conservative — when in doubt about whether something changed, do NOT flag it.
7. Output ONLY valid JSON — no explanation, no markdown fences.\
"""

CHAPTER_COMPARE_PROMPT = """\
You are comparing a section of the 2026 Massachusetts Driver's Manual against the
COMPLETE {old_year} edition. Read BOTH texts fully before forming any judgments.

══════════════════ COMPLETE {old_year} MANUAL ══════════════════
{old_text}

══════════════════ 2026 MANUAL (this section only) ══════════════════
{new_text}

══════════════════ YOUR TASK ══════════════════

For every topic in the 2026 text above, search the COMPLETE {old_year} manual to find
whether that topic existed. Report only genuine changes:

(a) Topic appears in 2026 but NOT ANYWHERE in the {old_year} manual → change_type "new"
(b) Topic appears in BOTH but the requirements, fines, or rules are different → change_type "updated" or "expanded"

Do NOT report:
- Topics that exist in both editions (even if reworded, in a different chapter, or at a different page)
- Minor clarifications or rewording that conveys the same rule
- Any content from the 2026 text that already exists in the {old_year} manual

Return this exact JSON structure:
{{
  "chapter_overview": "2-3 sentences on the most important changes found, or exactly: No significant changes in this section.",
  "changes": [
    {{
      "id": "kebab-case-unique-id",
      "title": "Descriptive topic title (e.g. Hands-Free Law, Failure-to-Stop Fine)",
      "change_type": "new" | "updated" | "expanded",
      "description": "One sentence explaining what changed and why it matters.",
      "bullets": [
        "\\"exact text copied from the 2026 manual\\" (2026 Massachusetts Driver's Manual)",
        "\\"another exact quote\\" (2026 Massachusetts Driver's Manual)"
      ],
      "images": []
    }}
  ]
}}

If there are no genuine changes in this section of the 2026 manual, return an empty changes array.\
"""

REMOVED_CONTENT_PROMPT = """\
Below is a list of topics from the {old_year} Massachusetts Driver's Manual that do not
appear to have a clear match in the 2026 edition.

For each topic, determine: is this content GENUINELY ABSENT from the 2026 manual, or does
it appear somewhere in the 2026 text shown below (possibly under a different heading)?

{old_year} TOPICS TO CHECK:
{old_topics}

2026 MANUAL FULL TEXT (search here):
{new_full_text}

Return a JSON array. Include ONLY topics that are genuinely absent from the 2026 manual:
[
  {{
    "title": "Topic title from {old_year} edition",
    "description": "One sentence explaining what was removed.",
    "bullets": [
      "\\"exact quote of the removed requirement\\" ({old_year} Massachusetts Driver's Manual)"
    ]
  }}
]\
"""

OVERVIEW_PROMPT = """\
Based on the following changes identified between the {old_year} and 2026 Massachusetts
Driver's Manual, write a SHORT 2-4 sentence plain-language summary that orients a driver
to the key NEW areas worth reviewing.

Changes:
{changes_summary}

Requirements:
- 2 to 4 sentences total. No headings, no bullet points, no JSON.
- Summarize and group the key new topic areas in your own words. Name several specific
  new topics (e.g. "such as Advanced Driver Assistance Systems, recommended car safety
  kits, proper backing-up technique...").
- Do NOT quote the manual directly and do NOT include citations — this is a paraphrased
  orientation, not the detailed change list.
- Write in plain language. Return only the summary text.\
"""


def _parse_json(raw: str) -> object:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


class LLMAnalyzer(ABC):

    @abstractmethod
    def compare_chapters(
        self,
        chapter_title: str,
        old_year: int,
        old_text: str,
        new_year: int,
        new_text: str,
    ) -> dict:
        """
        Compare full chapter texts from two editions.

        Returns:
        {
          "chapter_overview": str,
          "changes": [
            { "id", "title", "change_type", "description", "bullets", "images" }
          ]
        }
        """

    @abstractmethod
    def find_removed_content(
        self, old_topics: list[dict], new_full_text: str, old_year: int
    ) -> list[dict]:
        """
        Given a list of old-edition topics not matched to any 2026 content,
        confirm which are genuinely absent from the 2026 manual.

        Returns: [{ "title", "description", "bullets" }]
        """

    @abstractmethod
    def generate_overview(self, changes: list[dict], old_year: int) -> str:
        """Generate a plain-language overview paragraph."""


class ClaudeAnalyzer(LLMAnalyzer):
    def __init__(self):
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-opus-4-8"

    def _call(self, prompt: str, max_tokens: int = 8192) -> str:
        for attempt in range(3):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"    API error (attempt {attempt + 1}): {e}, retrying in 5s...")
                time.sleep(5)

    def compare_chapters(
        self,
        chapter_title: str,
        old_year: int,
        old_text: str,
        new_year: int,
        new_text: str,
    ) -> dict:
        """
        Compare a 2026 chunk against the complete old manual.
        Uses Anthropic prompt caching on the old_text (stable across all chunks).
        """
        import anthropic

        # Build prompt in two parts so we can cache the old_text block
        old_block = (
            f"══════════════════ COMPLETE {old_year} MANUAL ══════════════════\n"
            f"{old_text}\n\n"
        )
        new_block = (
            f"══════════════════ 2026 MANUAL (this section only) ══════════════════\n"
            f"{new_text}\n\n"
            f"══════════════════ YOUR TASK ══════════════════\n\n"
            "For every topic in the 2026 text above, search the COMPLETE "
            f"{old_year} manual to find whether that topic existed. Report only genuine changes:\n\n"
            f"(a) Topic appears in 2026 but NOT ANYWHERE in the {old_year} manual → change_type \"new\"\n"
            "(b) Topic appears in BOTH but requirements, fines, or rules are different → change_type \"updated\" or \"expanded\"\n\n"
            "Do NOT report:\n"
            "- Topics that exist in both editions (even if reworded, different chapter, or different page)\n"
            "- Minor clarifications that convey the same rule\n\n"
            "Return this exact JSON structure:\n"
            '{"chapter_overview": "2-3 sentences on changes found, or: No significant changes in this section.", '
            '"changes": [{"id": "kebab-case-id", "title": "Topic title", '
            '"change_type": "new"|"updated"|"expanded", '
            '"description": "One sentence.", '
            '"bullets": ["\\"exact quote\\" (2026 Massachusetts Driver\'s Manual)"], "images": []}]}'
        )

        for attempt in range(3):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    system=SYSTEM_PROMPT,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": old_block,
                                "cache_control": {"type": "ephemeral"},  # cache old manual
                            },
                            {
                                "type": "text",
                                "text": new_block,
                            },
                        ],
                    }],
                )
                raw = response.content[0].text
                result = _parse_json(raw)
                result.setdefault("chapter_overview", "")
                result.setdefault("changes", [])
                for ch in result["changes"]:
                    ch.setdefault("images", [])
                return result
            except json.JSONDecodeError as e:
                if attempt == 2:
                    print(f"\n    JSON parse error: {e}. Returning empty result.")
                    return {"chapter_overview": "", "changes": []}
                print(f"\n    JSON error (attempt {attempt + 1}), retrying...")
                time.sleep(3)
            except Exception as e:
                if attempt == 2:
                    print(f"\n    API error: {e}. Returning empty result.")
                    return {"chapter_overview": "", "changes": []}
                print(f"\n    API error (attempt {attempt + 1}): {e}, retrying in 5s...")
                time.sleep(5)

        return {"chapter_overview": "", "changes": []}

    def find_removed_content(
        self, old_topics: list[dict], new_full_text: str, old_year: int
    ) -> list[dict]:
        if not old_topics:
            return []

        topics_text = "\n\n".join(
            f"TOPIC: {t['title']}\n{t['body_text'][:600]}"
            for t in old_topics
        )
        prompt = REMOVED_CONTENT_PROMPT.format(
            old_year=old_year,
            old_topics=topics_text,
            new_full_text=new_full_text[:50000],
        )

        for attempt in range(3):
            try:
                raw = self._call(prompt, max_tokens=4096)
                result = _parse_json(raw)
                if isinstance(result, list):
                    return result
                return []
            except (json.JSONDecodeError, Exception) as e:
                if attempt == 2:
                    print(f"    find_removed_content error: {e}")
                    return []
                time.sleep(3)
        return []

    def generate_overview(self, changes: list[dict], old_year: int) -> str:
        if not changes:
            return (
                f"The {old_year} and 2026 Massachusetts Driver's Manuals cover the same "
                "core content. No significant legal or regulatory changes were identified."
            )
        summary = "\n".join(
            f"- {c['title']}: {c.get('description', '')}" for c in changes
        )
        try:
            raw = self._call(
                OVERVIEW_PROMPT.format(old_year=old_year, changes_summary=summary),
                max_tokens=512,
            )
            return raw.strip()
        except Exception:
            return f"The 2026 manual includes updates compared to the {old_year} edition."


class OpenAIAnalyzer(LLMAnalyzer):
    """Swap-in for org's enterprise OpenAI account. Set ANALYZER_BACKEND=openai."""

    def __init__(self):
        import openai
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY not set")
        self.client = openai.OpenAI(api_key=api_key)
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o")

    def _call(self, prompt: str, max_tokens: int = 8192) -> str:
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            except Exception as e:
                if attempt == 2:
                    raise
                time.sleep(5)

    def compare_chapters(self, chapter_title, old_year, old_text, new_year, new_text):
        prompt = CHAPTER_COMPARE_PROMPT.format(
            chapter_title=chapter_title,
            old_year=old_year,
            old_text=old_text,     # no truncation — full manual
            new_text=new_text,
        )
        try:
            raw = self._call(prompt)
            result = _parse_json(raw)
            result.setdefault("chapter_overview", "")
            result.setdefault("changes", [])
            for ch in result["changes"]:
                ch.setdefault("images", [])
            return result
        except Exception as e:
            print(f"    OpenAI compare_chapters error: {e}")
            return {"chapter_overview": "", "changes": []}

    def find_removed_content(self, old_topics, new_full_text, old_year):
        if not old_topics:
            return []
        topics_text = "\n\n".join(
            f"TOPIC: {t['title']}\n{t['body_text'][:600]}" for t in old_topics
        )
        prompt = REMOVED_CONTENT_PROMPT.format(
            old_year=old_year,
            old_topics=topics_text,
            new_full_text=new_full_text[:50000],
        )
        try:
            raw = self._call(prompt, max_tokens=4096)
            result = _parse_json(raw)
            return result if isinstance(result, list) else []
        except Exception as e:
            print(f"    OpenAI find_removed_content error: {e}")
            return []

    def generate_overview(self, changes, old_year):
        if not changes:
            return f"No significant changes identified between the {old_year} and 2026 editions."
        summary = "\n".join(f"- {c['title']}: {c.get('description', '')}" for c in changes)
        try:
            raw = self._call(
                OVERVIEW_PROMPT.format(old_year=old_year, changes_summary=summary),
                max_tokens=400,
            )
            return raw.strip()
        except Exception:
            return f"The 2026 manual includes updates compared to the {old_year} edition."


class LocalAnalyzer(LLMAnalyzer):
    """
    Token-free fallback using difflib. Lower accuracy; no API required.
    Install: pip install -r scripts/requirements-local.txt
    """

    def compare_chapters(self, chapter_title, old_year, old_text, new_year, new_text):
        import difflib
        ratio = difflib.SequenceMatcher(None, old_text, new_text).ratio()
        if ratio > 0.90:
            return {"chapter_overview": "No significant changes in this chapter.", "changes": []}
        return {
            "chapter_overview": f"Text differs between {old_year} and 2026 editions (similarity {ratio:.0%}).",
            "changes": [{
                "id": f"ch-{chapter_title.lower().replace(' ', '-')}-changes",
                "title": f"{chapter_title} (Local diff)",
                "change_type": "updated",
                "description": f"Text differs (similarity {ratio:.0%}). Run with LLM backend for details.",
                "bullets": [],
                "images": [],
            }],
        }

    def find_removed_content(self, old_topics, new_full_text, old_year):
        import difflib
        removed = []
        for t in old_topics:
            ratio = difflib.SequenceMatcher(None, t["body_text"][:400], new_full_text[:400]).ratio()
            if ratio < 0.15:
                removed.append({
                    "title": t["title"],
                    "description": f"Topic appears absent from 2026 edition.",
                    "bullets": [],
                })
        return removed

    def generate_overview(self, changes, old_year):
        n = len(changes)
        return f"Local diff identified {n} potential changes between the {old_year} and 2026 editions."


def get_analyzer() -> LLMAnalyzer:
    backend = os.environ.get("ANALYZER_BACKEND", "claude").lower()
    if backend == "claude":
        return ClaudeAnalyzer()
    elif backend == "openai":
        return OpenAIAnalyzer()
    elif backend == "local":
        return LocalAnalyzer()
    else:
        raise ValueError(f"Unknown ANALYZER_BACKEND: {backend!r}. Use claude, openai, or local.")
