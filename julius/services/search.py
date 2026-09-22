from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import replace

from rapidfuzz import fuzz, process

from julius.domain.comparison_basis import basis_value, comparison_basis
from julius.domain.models import PriceRecord, SearchOutcome
from julius.domain.normalization import normalize_text
from julius.repositories import prices, products

MATCH_SCORE_CUTOFF = 80
"""Minimum _name_score (0-100) for a product name to count as a match.

Measured on the real catalog (105 products, AI-written names): every whole-word or prefix hit
scores 100 ("pao" -> the 5 "Pão ..." products, "refri" -> both "Refrigerante ..."), and a
one-edit typo on a short word scores 80 ("arros" -> "Arroz", "pcanha" -> "Picanha" 92). The
false positives that survive at 80 all score exactly 80 and are the price of that typo
tolerance: "pao" -> "Cacau em pó", "vinho" -> "Pão Zinho", "queijo" -> "Requeijão",
"refri" -> "Resfriada". 81 would drop them and every one-edit typo with them.

This replaced fuzz.WRatio, which was measured inverting the ranking: WRatio penalizes a short
term against a long name, so "pao" scored 60 against "Pão de forma Bauducco tradicional 390g"
(dropped) and 72 against "Laranja pera União" (kept, via partial match on "UNIAO"). `consultar
pao` returned 12 fruits and 1 bread; no cutoff value fixes that, only a different scorer.
Two-edit typos stay out, same limitation already accepted by TAG_MATCH_CUTOFF ("pikana" ->
"Picanha" is 77). Known ceiling at the other end: the prefix comparison scores 100 for any name
word starting with the term, so a 1-2 letter term is a prefix listing ("a" and "pa" each match
22 of the 105 products). Wide but never wrong, so no minimum term length is enforced.
"""

NEAR_MISS_CUTOFF = 75
"""Minimum fuzz.ratio (0-100) between the term and a single word of a non-matching name for a
"did you mean" suggestion.

Was 70 until a real incident (2026-09-20, production catalog, 298 products): "quanto tá o kg de
alcatra" (a cut of beef, not in the catalog) suggested "Cerveja Heineken lata..." as an
alternative -- "alcatra" scored 72.7 against the single word "lata", coincidental shared letters
(a-l-a-t-a), not a plausible typo. Re-measuring the same real catalog with a broad sweep of common
grocery terms not yet in it turned up two more of the same shape, both worse (cross-category,
nothing food-related in common): "maminha" (a cut of beef) -> "Maizena" 71.4, "patinho" (a cut of
beef) -> "...com gatilho" (a spray bottle's trigger) 71.4. Raising the cutoff from 70 to 75 drops
all three while leaving every real match intact: "pikana" -> PICANHA stays at 76.9, and "arros"
-> "ARR" (the other case the previous docstring cited from the 5 original receipts) stays at 75.

Known residual false positives at 75, not chased further: "morango" (strawberry) -> "frango"
(chicken) 76.9, "farinha" (flour) -> "Fraldinha" (a cut of beef) 75, "mortadela" (a deli meat) ->
"framboesa"/"Mamão" (raspberry jam / papaya) 75-77 -- all score in the same band as the genuine
"pikana"->PICANHA match, so no cutoff value separates them from real typos without also losing
that match. This is the same shape of limitation this project already accepts for "queijo"->QUERO
(see history below) and for KIND_MATCH_CUTOFF's ties: a real limitation of a cheap word-level
string metric applied to short, generic words, not a bug to chase without a concrete wrong answer
observed in use -- and going further (real semantics) is exactly what this project's design
rejects as disproportionate for a personal catalog of a few hundred items (see
"Identidade de produto e busca" in CLAUDE.md).

Original measurement (70, on the 5 real receipts, 105 products): "pikana" -> PICANHA 77 and
"arros" -> ARR 75 stayed in; "frango" -> FGO 67 and "sabao" -> ARBO 67 stayed out. Known false
positive at the time: "queijo" -> QUERO 73 (now excluded too, at 75 -- no test ever required it,
it was only ever documented as accepted, not desired).
"""

NEAR_MISS_MAX_LEN_DIFF = 2
"""Same 2026-09-20 incident as NEAR_MISS_CUTOFF: fuzz.ratio alone doesn't penalize comparing
strings of very different lengths, the same shape of bug MATCH_SCORE_CUTOFF's docstring already
documents for WRatio -- "alcatra" (7 letters) against "lata" (4 letters) is a length gap of 3.
Kept as defense in depth alongside the raised cutoff (a longer coincidental overlap could in
principle still clear 75): a max length difference of 2 drops "lata" (diff 3) while leaving every
match in NEAR_MISS_CUTOFF's docstring (all diff 0-1) untouched."""

CONNECTIVE_WORDS = frozenset({"DE", "DA", "DO", "DAS", "DOS", "E"})
"""Term words that carry no product identity and are dropped before scoring (normalized form, so
uppercase and unaccented). Real incident (2026-09-20, production catalog, 133 products): "quanto tá
o suco de uva" -> the model extracted "suco de uva", and _name_score requires EVERY term word to
find a close word in the name, so "DE" (scoring 20-67 against every word of every juice name) sank
all three grape juices actually in the catalog ("Suco OQ integral 1,5L uva", "Suco Integral
Parreiras do Sul GF 1,5L Uva", "Suco pronto Natural One uva e maçã 1,3L" -- each scores 100 on
"suco uva"). The zero-result path then offered the Natural One back as a "category alternative",
so the bot said "sem preço registrado" and quoted a grape juice price in the same breath.

Deliberately NOT in the set: "COM"/"SEM" ("Água com gás" vs "Água sem gás" is a real distinction
this catalog carries) and any noun. Only removed from the *term*: extra words in a *name* were
never penalized. A term made only of these words falls back to the unfiltered words, so it still
scores like before instead of matching nothing."""

TAG_MATCH_CUTOFF = 75
"""Minimum fuzz.ratio (0-100) for a free-text word to count as a tag (v2.1, natural `consultar`).

Measured against the 13 seeded tags (see migration 0002) with fuzz.ratio on normalize_text: the
71 unique descriptions of the 6 real fixtures plus common grocery words (leite, arroz, queijo,
carne...). Worst real false positive is "PAPRICA" vs "PADARIA" = 71.4 ("TEMP" -> "TEMPEROS" and
"DESC" -> "DOCES" both 66.7). Worst 1-edit typo that must still match is 80.0 ("FIROS"/"FROIS" ->
"FRIOS", "AOCES" -> "DOCES"). 75 keeps margin on both sides. 2-edit typos (e.g. "AACES" vs
"DOCES" = 60) fall outside any reasonable cutoff, same limitation already accepted by
MATCH_SCORE_CUTOFF for product names. No two of the 13 tags score above 55 against each other.
"""


def search_prices(
    conn: sqlite3.Connection,
    term: str | None = None,
    tag: str | None = None,
    limit: int = 20,
) -> list[PriceRecord]:
    if term is None and tag is None:
        raise ValueError("term or tag is required")
    return records_for_products(conn, sorted(_candidate_ids(conn, term, tag)), limit)


def known_tags(conn: sqlite3.Connection) -> list[str]:
    """The tag vocabulary, for callers outside `repositories` reach (the bot layer never imports
    `repositories` directly -- see the DAG rules in CLAUDE.md)."""
    return products.all_tag_names(conn)


def known_kinds(conn: sqlite3.Connection) -> list[str]:
    """The kind vocabulary, for callers outside `repositories` reach -- same shape as
    `known_tags`. Consumed by `bot/agent.py`'s dynamic system prompt (docs/design/
    kind-resolution-in-routing.md): the routing model is told these exact spellings so it can
    already return one of them for `check_price`/`compare_stores`, instead of free text that
    `match_kind` then has to bridge alone."""
    return products.all_kinds(conn)


def detect_tag(conn: sqlite3.Connection, words: Sequence[str]) -> tuple[str | None, str | None]:
    """Tests each word of `words` against the known tags; the single best-scoring word above
    TAG_MATCH_CUTOFF (if any) is consumed as the tag, the rest re-joined as the term."""
    tags = products.all_tag_names(conn)
    if not tags or not words:
        return " ".join(words) or None, None
    normalized_tags = [normalize_text(t) for t in tags]
    best_index: int | None = None
    best_tag: str | None = None
    best_score = -1.0
    for index, word in enumerate(words):
        match = process.extractOne(normalize_text(word), normalized_tags, scorer=fuzz.ratio, score_cutoff=TAG_MATCH_CUTOFF)
        if match is not None and match[1] > best_score:
            best_index, best_tag, best_score = index, tags[match[2]], match[1]
    if best_index is None:
        return " ".join(words) or None, None
    remaining = [word for i, word in enumerate(words) if i != best_index]
    return " ".join(remaining) or None, best_tag


KIND_MATCH_CUTOFF = 75
"""Minimum _name_score (0-100) for a shopping-list term ("leite") to count as a known `kind`
("leite uht"). Measured on the 98 real kinds of the production catalogue (2026-09-19): whole-
string fuzz.ratio (ticket 176's first attempt) was reproduced and rejected the same way WRatio
was for product names (see MATCH_SCORE_CUTOFF) -- it penalizes a short generic term against a
longer compound kind so badly that real terms lost to unrelated kinds outright: "leite" scored
71 against "leite uht" (below any safe cutoff) while "agua" scored 67 against "manga" and only 50
against "água mineral", so a lowered cutoff would have matched the wrong kind, not just missed
the right one. Switching to _name_score (word-level, with the same prefix bonus product-name
matching already uses) fixes this: every generic single-word term tested ("leite", "pão"/"pao",
"água"/"agua", "carne", "arroz", "queijo", "creme", "suco", "maçã"/"maca") scores 92-100 against
its real kind, while the worst false positive among unrelated real terms is 66.7 ("feijao" vs
"requeijão", "cebola" vs "sacola reutilizável", "tomate" vs "manteiga") -- 75 sits in the open
gap between them, same margin TAG_MATCH_CUTOFF already relies on for the same scorer family.
Known ambiguity, not fixed by any cutoff: a generic term can tie 100 against more than one real
kind ("queijo" ties queijo brie/mussarela/parmesão; "leite" ties leite uht/condensado and creme
de leite) -- match_kind returns whichever sorts first alphabetically (all_kinds() is already
sorted), which is not always the most obviously "generic" one. Accepted the same way "queijo" ->
"QUERO" (NEAR_MISS_CUTOFF) was: a real limitation of matching a word against a vocabulary that
was never designed to be unambiguous, not a bug to chase without a concrete wrong answer observed
in use.

One tie IS resolved (ticket shopping-verdict-shape, 2026-09-19, real bug observed in use):
measured live against the production catalogue, `match_kind(conn, "tomate")` returned
"passata de tomate" instead of "tomate" -- both score 100 (whole-word match), and alphabetical
order put the wrong one first. "maca" -> "macarrão" instead of "maçã" is the same shape. When the
term, normalized, equals a tied kind's own normalized text exactly, that kind wins outright,
before falling back to the alphabetical order above for every other tie. Measured against the 98
real kinds and every generic term already documented above: only "tomate" and "maca" change;
"leite" (no kind is exactly "leite") is untouched, on purpose -- picking a different tie-break for
an inexact tie is a new guess, not a fix, without its own measured evidence."""


KIND_NOISE_WORDS = frozenset({
    "UM", "UMA", "UNS", "UMAS",
    "LITRO", "LITROS", "MILILITRO", "MILILITROS",
    "QUILO", "QUILOS", "GRAMA", "GRAMAS",
    "UNIDADE", "UNIDADES",
})
"""Term words stripped before match_kind scores, on top of what _name_score already drops
(CONNECTIVE_WORDS) -- articles and spelled-out units that a live-price question naturally carries
("uma coca", "refrigerante de 2 litros") but no `kind` value ever contains: measured against the
98 real kinds, zero collisions. Bare unit *letters* (L, KG, G, UN, ML) are handled separately by
_QUANTITY_TOKEN below, because in real phrasing they arrive glued to the number ("2L", "500G"),
not as their own word.

Real incident (2026-09-21, production catalog, bot channel): "Devo comprar uma coca por 12 reais?"
and "Devo comprar um refrigerante por 12 reais de 2 litros?" both came back reason=unknown_item
even though "refrigerante" alone scores 100 against its own kind -- _name_score requires EVERY term
word to find a match, and "uma"/"2"/"litros" match nothing in any kind, dragging the minimum below
KIND_MATCH_CUTOFF. Same shape of bug CONNECTIVE_WORDS already fixed for "suco de uva" (v2.8), for
the word class a live-price question introduces that plain search terms mostly don't."""

_QUANTITY_TOKEN = re.compile(r"^[0-9]+([.,][0-9]+)?[A-Z]{0,4}$")
"""A term word that is a bare number or a number glued to a unit ("2", "1,5L", "500G", "30UN") --
never part of a `kind`'s identity. Stripped alongside KIND_NOISE_WORDS in match_kind."""


def _strip_kind_noise(words: Sequence[str]) -> list[str]:
    filtered = [word for word in words if word not in KIND_NOISE_WORDS and not _QUANTITY_TOKEN.match(word)]
    return filtered or list(words)


def _score_kinds(conn: sqlite3.Connection, term_words: Sequence[str]) -> tuple[float, str | None, tuple[str, ...]]:
    """Scores `term_words` against every known `kind` once -- the one place the tie-break lives,
    shared by `match_kind` (resolve or refuse) and `kind_candidates` (what to offer on refusal).
    Returns `(best_score, resolved_kind, tied_candidates)`: `resolved_kind` is `None` exactly when
    `tied_candidates` is non-empty (a genuine unresolved tie, 2+ kinds at the best score with none
    exactly matching the term) or when nothing cleared `KIND_MATCH_CUTOFF`."""
    kinds = products.all_kinds(conn)
    if not kinds:
        return 0.0, None, ()
    scored = [(_name_score(term_words, normalize_text(kind).split()), kind) for kind in kinds]
    best_score = max(score for score, _ in scored)
    if best_score < KIND_MATCH_CUTOFF:
        return best_score, None, ()
    tied = [kind for score, kind in scored if score == best_score]
    if len(tied) == 1:
        return best_score, tied[0], ()
    term_norm = " ".join(term_words)
    exact = [kind for kind in tied if " ".join(normalize_text(kind).split()) == term_norm]
    if exact:
        return best_score, exact[0], ()
    return best_score, None, tuple(sorted(tied))


def match_kind(conn: sqlite3.Connection, term: str) -> str | None:
    """One term, one kind -- unlike detect_tag (a list of words competing for one tag), each item
    of a shopping list is matched independently. No kind registered yet -> None, without paying
    for a rapidfuzz call that could not possibly match anything.

    Uses _name_score (word-level, prefix-aware), not whole-string fuzz.ratio: a `kind` vocabulary
    mixes single words ("tomate") with compounds ("leite uht"), the same short-term-vs-long-name
    shape that already broke product-name matching before v2.3.1 -- see KIND_MATCH_CUTOFF.

    An unresolved tie against the vocabulary itself (2+ kinds at the same best score, none of them
    exactly the term) is `None`, not a silent alphabetical pick -- reversed 2026-09-22 after a real
    monkey-test incident: "queijo" tied "pão de queijo" against every real cheese kind (queijo
    mussarela/parmesão/brie), and alphabetical order picked the bread, so a live cheese price got
    compared against frozen cheese bread. `kind_candidates` exposes the tied options so
    `bot/actions.py::_resolve_kind` can ask instead of guess (docs/design/kind-resolution-in-
    routing.md, Decisão 3, extended). This is a real behavior change from the tie this project
    accepted in v2.10 ("leite" -> "creme de leite" silently): that tie was measured as low-stakes
    (still dairy); "queijo" -> bread is not the same shape, and asking is now the default for any
    tie without an exact-match winner -- see MEASURED note in kind_candidates for how many real
    single-word terms this touches.

    Falls back to product-name resolution (`_match_kind_via_product`) when no `kind` value itself
    matches -- a brand ("coca", "pepsi") has no `kind` of its own, only the category it belongs to
    ("refrigerante") does. Also consulted, and preferred, when the direct match barely clears
    KIND_MATCH_CUTOFF (score exactly at the cutoff, not above it): real incident, "coca" scores
    exactly 75 against "cacau em pó" (`fuzz.ratio("COCA", "CACAU"[:4])`, the same prefix trick that
    lets "refri" reach "REFRIGERANTE" catching a coincidental 4-letter overlap) while resolving
    cleanly to "refrigerante" through the two real Coca-Cola products. Scoped to exactly-at-cutoff
    on purpose, the same band MATCH_SCORE_CUTOFF's and NEAR_MISS_CUTOFF's docstrings already
    document as where a coincidental overlap survives, never above it -- a confident fuzzy match
    like "pikana" -> "picanha" (76.9, a typo one edit away) is not second-guessed, only measured to
    confirm it doesn't land exactly on 75 too.

    In that same borderline band, if the product fallback itself finds 2+ disagreeing kinds
    (genuine brand ambiguity, not a single confident correction), this returns `None` rather than
    the coincidental direct match -- found by `advisor` review, not observed in production yet:
    without this, a term landing exactly on the cutoff *and* matching two real, disagreeing
    products would silently keep the coincidence (`match_kind` non-`None`), and `kind_candidates`
    would never even be consulted (`_resolve_kind` only calls it when `match_kind` refused). `None`
    here is what lets that ambiguity surface as a question instead of a guess."""
    term_words = _strip_kind_noise(normalize_text(term).split())
    best_score, direct, tied = _score_kinds(conn, term_words)
    if tied:
        return None
    if direct is None:
        return _match_kind_via_product(conn, term_words)
    if best_score == KIND_MATCH_CUTOFF:
        found = _kinds_via_product(conn, term_words)
        if len(found) > 1:
            return None
        if len(found) == 1 and next(iter(found)) != direct:
            return next(iter(found))
    return direct


def _kinds_via_product(conn: sqlite3.Connection, term_words: Sequence[str]) -> frozenset[str]:
    """The `kind`s of every product `term_words` matches by name (`matching_product_ids`, the same
    calibrated matcher `search_prices` uses) -- the raw evidence both `_match_kind_via_product`
    (resolve when unanimous) and `kind_candidates` (offer when it's not) are built from."""
    term = " ".join(term_words)
    if not term:
        return frozenset()
    ids = matching_product_ids(conn, term)
    return frozenset(
        product.kind for product in products.list_products(conn) if product.id in ids and product.kind is not None
    )


def _match_kind_via_product(conn: sqlite3.Connection, term_words: Sequence[str]) -> str | None:
    """When no `kind` name itself matches, resolves via product name instead -- the same
    calibrated matcher `search_prices` already uses (`matching_product_ids`, MATCH_SCORE_CUTOFF),
    reused instead of a hand-maintained brand-to-kind list that would need a new entry for every
    brand the catalog ever gains. Real incident: "coca" and "pepsi" have no `kind` of their own
    (both live under kind "refrigerante"), but "coca" already matches exactly the two Coca-Cola
    products by name. Resolves only when every matched product agrees on the same kind -- "pepsi"
    also brushes "Cream cheese President" (a known false positive of the word-level scorer, see
    MATCH_SCORE_CUTOFF's docstring), and the two disagree on kind, so this stays unresolved
    (`None`) rather than guessing between them; `kind_candidates` is where that disagreement
    surfaces instead of being discarded."""
    found = _kinds_via_product(conn, term_words)
    return next(iter(found)) if len(found) == 1 else None


def kind_candidates(conn: sqlite3.Connection, term: str) -> tuple[str, ...]:
    """What `match_kind` knows but discards when it refuses -- either a genuine tie against the
    `kind` vocabulary itself (2+ kinds at the same score, none exactly the term: "queijo" ties
    "queijo mussarela"/"parmesão"/"brie" and "pão de queijo") or brand ambiguity (2+ real products
    disagreeing on kind, via `_match_kind_via_product`) -- the same information `resolve_product`
    already exposes so the bot can ask the person instead of guessing (docs/design/
    kind-resolution-in-routing.md, Decisão 3).

    **Reversed 2026-09-22**: until this date the direct-vocabulary tie was deliberately excluded
    here (`match_kind` picked one silently, "leite" -> "creme de leite", accepted since v2.10) --
    a second monkey-test round found "queijo" -> "pão de queijo" (alphabetically first, 'p' < 'q'),
    a live cheese price compared against frozen bread, and that crossed from "low-stakes dairy
    tie" to "wrong category entirely". `match_kind` now returns `None` for any unresolved tie, and
    this surfaces it every time, not just for "queijo".

    Measured against the 98 real kinds (2026-09-22) for the effect on already-relied-upon generic
    single-word terms (`KIND_MATCH_CUTOFF`'s own list) -- bigger than the one incident that
    triggered this reversal:

    | term | now asks between |
    |---|---|
    | leite | creme de leite, leite condensado, leite uht |
    | pão | pão australiano, baguete, de alho, de forma, de queijo |
    | água | água com gás, água mineral |
    | queijo | pão de queijo, queijo brie, mussarela, parmesão, parmesão ralado |
    | creme | creme de leite, creme de ricota |

    "tomate" and "maca" are untouched (the exact-match shortcut still wins those ties outright);
    "carne", "arroz", "suco", "cebola" have no tie at all and are also untouched. Five real generic
    terms trade a silent (sometimes wrong, as "queijo" -> bread just proved) answer for one extra
    question -- a bigger trade than "queijo" alone, and worth knowing it's five, not one, before
    calling this closed. Accepted as the right side of that trade given the concrete harm the
    alternative just caused; revisit if asking this often for "pão"/"leite" reads as annoying in
    real use, which is exactly the kind of evidence this project has always required to re-tune a
    cutoff either direction.

    Checks `match_kind` itself first, rather than trusting the caller to only ask when it already
    returned `None`: this is what makes the scope boundary above true by construction. The extra
    `match_kind` call is cheap (same cost this project already pays everywhere else for a personal
    catalog of a few hundred products)."""
    if match_kind(conn, term) is not None:
        return ()
    term_words = _strip_kind_noise(normalize_text(term).split())
    _, _, tied = _score_kinds(conn, term_words)
    if tied:
        return tied
    found = _kinds_via_product(conn, term_words)
    return tuple(sorted(found)) if len(found) > 1 else ()


def search_free_text(
    conn: sqlite3.Connection, words: Sequence[str], tag: str | None = None, limit: int = 20
) -> SearchOutcome:
    """Entry point for `consultar` with free-text words. If `tag` is given explicitly, tag
    detection never runs. Otherwise, a word that matches a known tag is used as a filter
    (intersected with the rest as the term); an empty intersection is retried as a plain term."""
    if tag is not None:
        term = " ".join(words) or None
        return SearchOutcome(tuple(search_prices(conn, term=term, tag=tag, limit=limit)), term, tag)
    remaining_term, detected_tag = detect_tag(conn, words)
    if detected_tag is None:
        records = search_prices(conn, term=remaining_term, tag=None, limit=limit)
        return SearchOutcome(tuple(records), remaining_term, None)
    records = search_prices(conn, term=remaining_term, tag=detected_tag, limit=limit)
    if records:
        return SearchOutcome(tuple(records), remaining_term, detected_tag, detected_tag)
    full_term = " ".join(words) or None
    records = search_prices(conn, term=full_term, tag=None, limit=limit)
    return SearchOutcome(tuple(records), full_term, None, detected_tag)


def records_for_products(conn: sqlite3.Connection, product_ids: Sequence[int], limit: int) -> list[PriceRecord]:
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    records = _collapse(prices.prices_for_products(conn, product_ids))
    groups: dict[str, list[PriceRecord]] = {}
    for record in records:
        groups.setdefault(record.unit, []).append(record)
    result: list[PriceRecord] = []
    for unit in sorted(groups):
        result.extend(_highlight_and_trim(groups[unit], limit))
    return result


def catalog_for_matching(conn: sqlite3.Connection) -> list[tuple[int, str, tuple[str, ...]]]:
    rows = [(product.id, product.canonical_name, product.tags) for product in products.list_products(conn)]
    return sorted(rows, key=lambda row: row[0])


def closest_names(conn: sqlite3.Connection, term: str, limit: int = 3) -> list[tuple[str, int]]:
    """Names that search_prices would NOT match but have one word close to the term, best first."""
    normalized_term = normalize_text(term)
    matched = matching_product_ids(conn, term)
    scores: dict[str, int] = {}
    for product_id, name in products.product_names(conn):
        if product_id in matched:
            continue
        score = max(
            (
                fuzz.ratio(normalized_term, word)
                for word in normalize_text(name).split()
                if abs(len(word) - len(normalized_term)) <= NEAR_MISS_MAX_LEN_DIFF
            ),
            default=0,
        )
        if score >= NEAR_MISS_CUTOFF:
            scores[name] = max(int(score), scores.get(name, 0))
    return sorted(scores.items(), key=lambda item: -item[1])[:limit]


WORD_LENGTH_GAP_LIMIT = 1
"""Real incident (2026-09-21, monkey test against the production catalog): `matching_product_ids`
matched "picanha" (a search for beef) to "Pinha" (id 112, a fruit) at score 83.3 -- above
MATCH_SCORE_CUTOFF, and high enough to mark the fruit's price as the group's cheapest in the reply
table. The prefix trick is a no-op in this direction (truncating "PINHA" to 7 characters, the
length of "PICANHA", changes nothing -- it is already shorter), so the whole-string coincidence
alone cleared the bar: a two-character deletion ("PICANHA" minus "CA") between two completely
unrelated products.

Measured against every pair of distinct words in the real catalog (150+ words, no substring
relationship) that scores >= MATCH_SCORE_CUTOFF in the *query-is-longer-than-catalog-word*
direction: every one of them is a coincidence between unrelated products, none is a required
match. The one required case that scores exactly at the cutoff in this same direction, "arros" ->
"Arroz" (both 5 letters, one substitution), has length gap 0 -- so does every other required
one-edit typo this project relies on (a substitution keeps length identical; the closest real
insertion/deletion case is "pcanha" -> "Picanha", but there the catalog word is *longer*, the
opposite direction, untouched by this guard). Gap 1 is kept with margin to spare; nothing measured
needs it. Scoped to only this direction on purpose: when the catalog word is longer than the query
(the abbreviation/prefix case, "refri" -> "REFRIGERANTE"), the same coincidence shape is the
*price* of that feature (see MATCH_SCORE_CUTOFF's "pao" -> "Cacau em pó" etc.) and is not touched
here -- fixing that direction too would need to weaken the prefix trick itself, unmeasured and
out of scope for one incident."""


def _word_score(word: str, other: str) -> float:
    """The best of whole-string and prefix similarity for one term word against one name word --
    see WORD_LENGTH_GAP_LIMIT for why a large length gap voids the whole-string score when `other`
    is the shorter one."""
    if len(other) <= len(word) and len(word) - len(other) > WORD_LENGTH_GAP_LIMIT:
        return 0.0
    return max(fuzz.ratio(word, other), fuzz.ratio(word, other[: len(word)]))


def _name_score(term_words: Sequence[str], name_words: Sequence[str]) -> float:
    """Every word of the term has to find a close word in the name: min over the term's words of
    the best per-word score. The prefix comparison is what keeps an abbreviated term matching
    ("refri" -> "REFRIGERANTE") without letting a substring anywhere in the name count, which is
    how "PAO" used to match "UNIAO". It only works in that direction: an abbreviation in the
    *name* ("LING" for linguiça) still misses, and the durable fix for that is the AI rename."""
    if not term_words or not name_words:
        return 0.0
    term_words = [word for word in term_words if word not in CONNECTIVE_WORDS] or term_words
    return min(max(_word_score(word, other) for other in name_words) for word in term_words)


def matching_product_ids(conn: sqlite3.Connection, term: str) -> set[int]:
    term_words = normalize_text(term).split()
    return {
        product_id
        for product_id, name in products.product_names(conn)
        if _name_score(term_words, normalize_text(name).split()) >= MATCH_SCORE_CUTOFF
    }


def _candidate_ids(conn: sqlite3.Connection, term: str | None, tag: str | None) -> set[int]:
    ids: set[int] | None = None
    if term is not None:
        ids = matching_product_ids(conn, term)
    if tag is not None:
        tagged = set(products.product_ids_with_tag(conn, tag.strip().lower()))
        ids = tagged if ids is None else ids & tagged
    return ids or set()


def _collapse(records: list[PriceRecord]) -> list[PriceRecord]:
    """One row per (group, day, store, price). The same price of the same product on the same day
    at the same store carries no price information twice — it is the item repeated in one receipt.
    Has to happen before the highlight, or the limit is spent on repetition."""
    seen: dict[tuple[int, str, str, float], PriceRecord] = {}
    for record in records:
        # By CNPJ: two branches of one chain share a nickname, and collapsing them would hide a
        # second real purchase behind the first.
        seen.setdefault((record.product_id, record.purchased_at, record.store_cnpj, record.unit_price), record)
    return list(seen.values())


def _highlight_and_trim(group: list[PriceRecord], limit: int) -> list[PriceRecord]:
    group = sorted(group, key=lambda record: record.purchased_at, reverse=True)
    basis, participants = comparison_basis(group)
    if basis == "price_per_content":
        # The question is "which package is worth it", so the useful order is the one the
        # highlight already uses. Rows with no content have no value on this basis and go last.
        group = sorted(group, key=lambda record: (record.price_per_content is None, record.price_per_content or 0.0))
        basis, participants = comparison_basis(group)
    values = {index: value for index in participants if (value := basis_value(group[index], basis)) is not None}
    if len(values) < 2:
        return group[:limit]
    lowest, highest = min(values.values()), max(values.values())
    kept = list(range(min(limit, len(group))))
    kept += [index for index in range(limit, len(group)) if values.get(index) in (lowest, highest)]
    if lowest == highest:
        return [group[index] for index in kept]
    return [
        replace(
            group[index],
            highlight="lowest"
            if values.get(index) == lowest
            else "highest"
            if values.get(index) == highest
            else None,
        )
        for index in kept
    ]
