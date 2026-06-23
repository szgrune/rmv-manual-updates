"""
Unit tests for scripts/lib/merge.py (multi-run change merging).
Run: python3 tests/merge_test.py    (no dependencies)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib.merge import merge_change_sets  # noqa: E402

passed = 0


def test(name, fn):
    global passed
    fn()
    passed += 1
    print(f"  ok  {name}")


def ch(id, title, type, bullets, chapter="X", chapter_num=4):
    return {"id": id, "title": title, "change_type": type, "bullets": bullets,
            "chapter": chapter, "chapter_num": chapter_num, "images": []}


ATTR = "(2023 Massachusetts Driver's Manual)"


def t_shared_quote_merges():
    q = f'"A partir del 1 de julio de 2023 ya no se requiere prueba de presencia legal." {ATTR}'
    run1 = [ch("wfma-a", "Ley WFMA", "new", [q])]
    run2 = [ch("wfma-b", "Movilidad laboral y familiar", "new", [q])]  # different title, same quote
    out = merge_change_sets([run1, run2])
    assert len(out) == 1, len(out)
    assert out[0]["id"] == "wfma-a", "first occurrence keeps id"


def t_similar_title_same_type_merges():
    qa = f'"el primer fragmento citado del manual con longitud suficiente." {ATTR}'
    qb = f'"un segundo fragmento totalmente distinto y bastante largo." {ATTR}'
    # Same topic, words reordered — token-set similarity must catch this.
    run1 = [ch("hf-1", "Ley de manos libres para dispositivos electrónicos móviles", "new", [qa])]
    run2 = [ch("hf-2", "Ley de dispositivos electrónicos móviles manos libres", "new", [qb])]
    out = merge_change_sets([run1, run2])
    assert len(out) == 1, [c["title"] for c in out]
    assert out[0]["id"] == "hf-1"
    # the distinct second quote is unioned in
    assert any("segundo fragmento" in b for b in out[0]["bullets"]), out[0]["bullets"]
    assert any("primer fragmento" in b for b in out[0]["bullets"])


def t_distinct_similar_titles_not_merged():
    # Same prefix, genuinely different topics — must NOT merge.
    run1 = [ch("d1", "Distancia de seguimiento segura", "updated", [f'"tres segundos." {ATTR}'])]
    run2 = [ch("d2", "Distancia de seguimiento de motocicletas", "updated", [f'"cuatro segundos." {ATTR}'])]
    out = merge_change_sets([run1, run2])
    assert len(out) == 2, [c["title"] for c in out]


def t_different_change_type_not_title_merged():
    # Similar titles but different change_type and no shared quote → keep both.
    run1 = [ch("a", "Carriles para bicicletas", "new", [f'"x." {ATTR}'])]
    run2 = [ch("b", "Carriles para bicicletas", "expanded", [f'"y." {ATTR}'])]
    out = merge_change_sets([run1, run2])
    assert len(out) == 2


def t_quote_dedup_tolerates_quote_marks_and_attr():
    plain = f'A partir del 7 de mayo de 2025 necesitará una REAL ID para volar. {ATTR}'
    quoted = f'"A partir del 7 de mayo de 2025 necesitará una REAL ID para volar." {ATTR}'
    run1 = [ch("r1", "REAL ID", "updated", [plain])]
    run2 = [ch("r2", "Fecha REAL ID", "updated", [quoted])]
    out = merge_change_sets([run1, run2])
    assert len(out) == 1, out


def t_union_drops_stale_citations():
    q1 = f'"primera cita lo bastante larga para contar como clave." {ATTR}'
    q2 = f'"segunda cita diferente y tambien suficientemente larga." {ATTR}'
    kept = ch("k", "Reporte de conducta inapropiada del oficial", "expanded", [q1])
    kept["citations"] = [{"year": 2023, "page": 5}]
    run2 = [ch("k2", "Reporte de conducta inapropiada del oficial", "expanded", [q2])]
    out = merge_change_sets([[kept], run2])
    assert len(out) == 1
    assert "citations" not in out[0], "stale citations dropped after bullet union"
    assert len(out[0]["bullets"]) == 2


def t_single_run_passthrough_and_internal_dedup():
    q = f'"texto identico citado dos veces en la misma corrida." {ATTR}'
    run1 = [ch("a", "Tema", "new", [q]), ch("b", "Otro tema distinto", "new", [f'"diferente cita." {ATTR}'])]
    out = merge_change_sets([run1])
    assert len(out) == 2
    # a duplicate within a single run is also collapsed
    run_dup = [ch("a", "Tema", "new", [q]), ch("a2", "Tema otra vez", "new", [q])]
    assert len(merge_change_sets([run_dup])) == 1


test("shared quote merges across runs (first id wins)", t_shared_quote_merges)
test("similar title + same type merges, unions quotes", t_similar_title_same_type_merges)
test("distinct topics with similar prefixes are NOT merged", t_distinct_similar_titles_not_merged)
test("similar title but different change_type not merged", t_different_change_type_not_title_merged)
test("quote dedup tolerates quote marks + attribution", t_quote_dedup_tolerates_quote_marks_and_attr)
test("bullet union drops stale citations", t_union_drops_stale_citations)
test("single run passthrough + internal dedup", t_single_run_passthrough_and_internal_dedup)

print(f"\n{passed} tests passed.")
