"""
Merge multiple analysis runs into one de-duplicated change set.

The LLM analysis is non-deterministic: each run over the same two editions finds a
somewhat different set of genuine changes. To maximize coverage we run the analysis
several times and merge the UNIQUE changes here.

Two changes (possibly from different runs) are treated as the SAME topic when:
  (a) they share a significant verbatim quote (the strongest signal — the same
      manual text was quoted), or
  (b) their titles are highly similar AND they have the same change_type
      (catches the same topic quoted via different sentences across runs).

When two changes merge, the FIRST occurrence (earliest run) is kept — it keeps its
id, title, description, chapter, change_type and images — and any *new* verbatim
quotes from the later occurrence are unioned into its bullets. Keeping the earliest
occurrence's id is deliberate: appending more runs never renames an existing change,
so manual overrides keyed by id stay valid across runs.

Pure module (no DB / IO) so it can be unit-tested in isolation.
"""

import difflib
import re
import unicodedata

# Trailing attribution on a quoted bullet, e.g. "(2023 Massachusetts Driver's Manual)".
_ATTR_RE = re.compile(r"\(\d{4}\s+Massachusetts[^)]*\)\s*$", re.I)

# A normalized quote shorter than this is too generic to be a reliable identity key.
_MIN_QUOTE_LEN = 24
# Quotes are compared by a leading prefix so small tail differences still match.
_QUOTE_PREFIX = 80
# Title-similarity above which same-change_type titles merge. Compared with a blend
# of token-set overlap (order-insensitive — handles reworded/reordered titles) and
# difflib ratio (character-level near-identity).
DEFAULT_TITLE_THRESHOLD = 0.78

# Common Spanish function words ignored when comparing titles by word set.
_STOPWORDS = frozenset(
    "de la el los las un una unos unas y o u a en para con su sus que del al lo".split()
)
# Cap bullets per merged change so unioning across many runs can't bloat a card.
_BULLET_CAP = 12


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _quote_text(bullet: str) -> str:
    """Strip the trailing attribution and any wrapping quote marks from a bullet."""
    return _ATTR_RE.sub("", bullet or "").strip().strip('"“”').strip()


def _quote_key(bullet: str) -> str:
    nq = _norm(_quote_text(bullet))
    return nq[:_QUOTE_PREFIX] if len(nq) >= _MIN_QUOTE_LEN else ""


def _quote_keys(change: dict) -> set:
    keys = set()
    for b in change.get("bullets") or []:
        k = _quote_key(b)
        if k:
            keys.add(k)
    return keys


def _title_tokens(title: str) -> set:
    return {w for w in _norm(title).split() if w not in _STOPWORDS and len(w) > 1}


def _title_similarity(a: str, b: str) -> float:
    """Blend token-set overlap (order-insensitive) with difflib char ratio."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    ta, tb = _title_tokens(a), _title_tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if (ta or tb) else 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    return max(jaccard, seq)


def _same_topic(a: dict, b: dict, title_threshold: float) -> bool:
    # (a) shared verbatim quote — strong, exact.
    if _quote_keys(a) & _quote_keys(b):
        return True
    # (b) very similar title + same change_type — same topic quoted differently.
    if a.get("change_type") == b.get("change_type"):
        if _title_similarity(a.get("title", ""), b.get("title", "")) >= title_threshold:
            return True
    return False


def _union_bullets(kept: dict, other: dict) -> None:
    """Append quotes from `other` that `kept` doesn't already have (by normalized key)."""
    bullets = list(kept.get("bullets") or [])
    have = {_quote_key(b) for b in bullets}
    have.discard("")
    for b in other.get("bullets") or []:
        if len(bullets) >= _BULLET_CAP:
            break
        k = _quote_key(b)
        if k and k not in have:
            bullets.append(b)
            have.add(k)
    if bullets != (kept.get("bullets") or []):
        kept["bullets"] = bullets
        # citations are derived from bullets at export time — drop any stale ones.
        kept.pop("citations", None)


def merge_change_sets(run_sets: list, title_threshold: float = DEFAULT_TITLE_THRESHOLD) -> list:
    """
    Merge a list of run change-sets (each a list of change dicts) into one list.
    `run_sets` must be in run order, earliest first, so the earliest occurrence of
    each topic wins its id. Returns merged change dicts in first-appearance order.
    """
    merged: list = []
    for sections in run_sets:
        for ch in sections or []:
            hit = next((k for k in merged if _same_topic(ch, k, title_threshold)), None)
            if hit is None:
                merged.append(dict(ch))      # copy; keeps first occurrence's fields/id
            else:
                _union_bullets(hit, ch)
    return merged
