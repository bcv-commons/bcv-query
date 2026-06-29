"""Context-Fabric data access layer for biblical texts."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import cfabric
from cfabric.core.api import Api

from corpus_engine.models import (
    BookInfo,
    FeatureInfo,
    ObjectTypeInfo,
    PassageResult,
    SchemaResult,
    VerseResult,
    WordInfo,
)

logger = logging.getLogger(__name__)

CORPORA = {
    "hebrew": ("ETCBC/bhsa", "Biblical Hebrew (BHSA)"),
    "greek": ("ETCBC/nestle1904", "Greek New Testament (Nestle 1904)"),
}

WORD_FEATURES = {
    "hebrew": {
        "text": "g_word_utf8",
        "trailer": "trailer_utf8",
        "lexeme": "lex",
        "lexeme_utf8": "lex_utf8",
        "gloss": "gloss",
        "part_of_speech": "sp",
        "gender": "gn",
        "number": "nu",
        "person": "ps",
        "state": "st",
        "verbal_stem": "vs",
        "verbal_tense": "vt",
        "language": "language",
        "suffix_feat": "prs",
    },
    "greek": {
        "text": "unicode",
        "trailer": "after",
        "lexeme": "lemma",
        "lexeme_utf8": "lemma",
        "gloss": "gloss",
        "part_of_speech": "cls",
        "gender": "gender",
        "number": "number",
        "person": "person",
        "state": "",
        "verbal_stem": "voice",
        "verbal_tense": "tense",
        "language": "",
    },
}

WORD_TYPE = {
    "hebrew": "word",
    "greek": "w",
}

_EXCLUDE_FEATURES: dict[str, set[str]] = {
    "greek": {"nodeId"},
}


def _find_corpus_path(org_repo: str) -> str:
    """Locate a TF-format corpus on disk."""
    home = os.environ.get("HOME", str(Path.home()))
    base = Path(home) / "text-fabric-data" / "github" / org_repo / "tf"
    if base.exists():
        versions = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)
        if versions:
            return str(versions[0])

    try:
        cache_dir = cfabric.get_cache_dir()
        alt = Path(cache_dir) / org_repo
        if alt.exists():
            return str(alt)
    except Exception:
        pass

    raise FileNotFoundError(
        f"Corpus data not found for {org_repo}. "
        f"Searched: {base}. HOME={home}. "
        "Ensure the corpus has been pre-downloaded."
    )


class CFEngine:
    """Manages Context-Fabric corpus loading and queries."""

    def __init__(self) -> None:
        self._apis: dict[str, Api] = {}
        self._fabrics: dict[str, cfabric.Fabric] = {}
        self._rank_maps: dict[str, dict[str, int]] = {}
        self._lex_strong: dict[str, dict[str, str]] = {}
        self._load_lock = threading.Lock()

    def _ensure_loaded(self, corpus: str) -> Api:
        """Load a corpus if not already loaded, return the CF Api."""
        if corpus not in CORPORA:
            raise ValueError(
                f"Unknown corpus '{corpus}'. Available: {list(CORPORA.keys())}"
            )
        if corpus in self._apis:
            return self._apis[corpus]
        with self._load_lock:
            if corpus in self._apis:
                return self._apis[corpus]
            org_repo, display_name = CORPORA[corpus]
            logger.info(
                "Loading %s (%s) via Context-Fabric ...", display_name, org_repo
            )

            path = _find_corpus_path(org_repo)
            logger.info("Corpus path: %s", path)

            exclude = _EXCLUDE_FEATURES.get(corpus, set())
            hidden: list[tuple[Path, Path]] = []
            for feat_name in exclude:
                tf_file = Path(path) / f"{feat_name}.tf"
                skip_file = tf_file.with_suffix(".tf._skip")
                if tf_file.exists():
                    tf_file.rename(skip_file)
                    hidden.append((skip_file, tf_file))
                    logger.info("Temporarily hidden: %s", tf_file)

            try:
                CF = cfabric.Fabric(locations=path, silent="deep")
                api = CF.loadAll(silent="deep")
            except Exception as e:
                logger.error("Context-Fabric load failed for %s: %s", path, e)
                raise RuntimeError(
                    f"Failed to load corpus '{corpus}' from {path}: {e}"
                ) from e
            finally:
                for skip_file, tf_file in hidden:
                    if skip_file.exists():
                        skip_file.rename(tf_file)
                        logger.info("Restored: %s", tf_file)

            if api is None or not hasattr(api, "T") or not hasattr(api.F, "otype"):
                raise RuntimeError(
                    f"Failed to load corpus '{corpus}' from {path}. "
                    "Context-Fabric API did not initialize correctly."
                )

            self._fabrics[corpus] = CF
            self._apis[corpus] = api
            logger.info("Loaded %s", display_name)

        return self._apis[corpus]

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def list_corpora(self) -> list[dict[str, str]]:
        return [{"id": cid, "name": display} for cid, (_, display) in CORPORA.items()]

    def list_books(self, corpus: str = "hebrew") -> list[BookInfo]:
        api = self._ensure_loaded(corpus)
        books = []
        for book_node in api.F.otype.s("book"):
            book_name = api.T.sectionFromNode(book_node)[0]
            chapter_nodes = api.L.d(book_node, otype="chapter")
            books.append(BookInfo(name=book_name, chapters=len(chapter_nodes)))
        return books

    def get_passage(
        self,
        book: str,
        chapter: int,
        verse_start: int = 1,
        verse_end: int | None = None,
        corpus: str = "hebrew",
    ) -> PassageResult:
        api = self._ensure_loaded(corpus)
        feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])

        if verse_end is None:
            verse_end = verse_start

        wtype = WORD_TYPE.get(corpus, "word")

        verses: list[VerseResult] = []
        for verse_num in range(verse_start, verse_end + 1):
            verse_node = api.T.nodeFromSection((book, chapter, verse_num))
            if verse_node is None:
                continue

            word_nodes = api.L.d(verse_node, otype=wtype)
            words: list[WordInfo] = []
            for w in word_nodes:
                words.append(self._word_info(api, w, feat_map))

            verses.append(
                VerseResult(
                    book=book,
                    chapter=chapter,
                    verse=verse_num,
                    words=words,
                )
            )

        return PassageResult(corpus=corpus, verses=verses)

    def get_schema(self, corpus: str = "hebrew") -> SchemaResult:
        api = self._ensure_loaded(corpus)

        object_types: list[ObjectTypeInfo] = []
        for otype in api.F.otype.all:
            nodes = api.F.otype.s(otype)
            count = len(nodes)
            if count == 0:
                continue

            sample_node = nodes[0]
            features: list[FeatureInfo] = []
            for feat_name in sorted(api.Fall()):
                feat_obj = api.Fs(feat_name)
                if feat_obj is None:
                    continue
                val = feat_obj.v(sample_node)
                if val is not None:
                    features.append(FeatureInfo(name=feat_name))

            object_types.append(
                ObjectTypeInfo(name=otype, count=count, features=features)
            )

        return SchemaResult(corpus=corpus, object_types=object_types)

    def search_words(
        self,
        corpus: str = "hebrew",
        book: str | None = None,
        chapter: int | None = None,
        features: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[dict]:
        api = self._ensure_loaded(corpus)
        wtype = WORD_TYPE.get(corpus, "word")

        constraints = []
        if features:
            for feat, val in features.items():
                constraints.append(f"  {feat}={val}")

        constraint_str = "\n".join(constraints)

        if book and chapter:
            template = (
                f"book book={book}\n"
                f"  chapter chapter={chapter}\n"
                f"    {wtype}\n{constraint_str}\n"
            )
        elif book:
            template = f"book book={book}\n  {wtype}\n{constraint_str}\n"
        else:
            template = f"{wtype}\n{constraint_str}\n"

        results = list(api.S.search(template))

        feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])
        output = []
        for result_tuple in results[:limit]:
            w = result_tuple[-1]
            section = api.T.sectionFromNode(w)
            info = self._word_info(api, w, feat_map)
            output.append(
                {
                    "book": section[0],
                    "chapter": section[1],
                    "verse": section[2],
                    "word": info.model_dump(),
                }
            )

        return output

    def search_constructions(
        self,
        template: str,
        corpus: str = "hebrew",
        limit: int = 50,
    ) -> list[dict]:
        api = self._ensure_loaded(corpus)
        feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])
        wtype = WORD_TYPE.get(corpus, "word")

        results = list(api.S.search(template))

        output = []
        for result_tuple in results[:limit]:
            entry: dict[str, Any] = {"objects": []}
            for node in result_tuple:
                otype = api.F.otype.v(node)
                section = api.T.sectionFromNode(node)
                obj: dict[str, Any] = {
                    "type": otype,
                    "book": section[0] if len(section) > 0 else "",
                    "chapter": section[1] if len(section) > 1 else 0,
                    "verse": section[2] if len(section) > 2 else 0,
                    "text": api.T.text(node),
                }
                if otype == wtype:
                    obj["word"] = self._word_info(api, node, feat_map).model_dump()
                else:
                    features = {}
                    for feat_name in sorted(api.Fall()):
                        feat_obj = api.Fs(feat_name)
                        if feat_obj is None:
                            continue
                        val = feat_obj.v(node)
                        if val is not None:
                            features[feat_name] = str(val)
                    obj["features"] = features
                entry["objects"].append(obj)
            output.append(entry)

        return output

    def get_context(
        self,
        book: str,
        chapter: int,
        verse: int,
        word_index: int = 0,
        corpus: str = "hebrew",
    ) -> dict:
        api = self._ensure_loaded(corpus)

        wtype = WORD_TYPE.get(corpus, "word")

        verse_node = api.T.nodeFromSection((book, chapter, verse))
        if verse_node is None:
            return {"error": f"Verse not found: {book} {chapter}:{verse}"}

        word_nodes = api.L.d(verse_node, otype=wtype)
        if word_index >= len(word_nodes):
            return {
                "error": f"Word index {word_index} out of range (max {len(word_nodes) - 1})"
            }

        w = word_nodes[word_index]
        feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])

        context: dict[str, Any] = {
            "word": self._word_info(api, w, feat_map).model_dump(),
        }

        all_types = [
            t for t in api.F.otype.all if t not in ("book", "chapter", "verse", wtype)
        ]
        for parent_type in all_types:
            parents = api.L.u(w, otype=parent_type)
            if parents:
                parent = parents[0]
                parent_features = {}
                for feat_name in sorted(api.Fall()):
                    feat_obj = api.Fs(feat_name)
                    if feat_obj is None:
                        continue
                    val = feat_obj.v(parent)
                    if val is not None:
                        parent_features[feat_name] = str(val)
                context[parent_type] = {
                    "node": int(parent),
                    "features": parent_features,
                    "text": api.T.text(parent),
                }

        return context

    def list_clauses(
        self,
        corpus: str = "hebrew",
        book: str | None = None,
        clause_type: str | None = None,
    ) -> list[dict]:
        """All clause-level units of a corpus (optionally one book), each with
        its text and start reference. The clause is the embedding unit for
        original-language semantic search (shoresh). BHSA has gold `clause`
        objects; Greek (Nestle1904) falls back to `sentence`."""
        api = self._ensure_loaded(corpus)
        otype = clause_type or ("clause" if corpus == "hebrew" else "sentence")
        if otype not in api.F.otype.all:
            return [{"error": f"corpus '{corpus}' has no object type '{otype}' "
                              f"(available: {', '.join(api.F.otype.all)})"}]

        if book:
            book_node = api.T.nodeFromSection((book,))
            if book_node is None:
                return [{"error": f"book not found: {book}"}]
            nodes = api.L.d(book_node, otype=otype)
        else:
            nodes = api.F.otype.s(otype)

        out: list[dict] = []
        for n in nodes:
            sec = api.T.sectionFromNode(n)
            if not sec:
                continue
            text = (api.T.text(n) or "").strip()
            if not text:
                continue
            out.append({
                "node": int(n),
                "book": sec[0],
                "chapter": sec[1] if len(sec) > 1 else None,
                "verse": sec[2] if len(sec) > 2 else None,
                "text": text,
            })
        return out

    def _lex_strong_map(self, corpus: str) -> dict[str, str]:
        """{lex: strong} from resources/word_freq/{hbo,grc}_strong.tsv, memoized per
        corpus. Built by `python -m corpus_engine.build_lex_strong`; lets /words
        attach a Strong's (and thence keyness) per word. Empty if the file is absent."""
        cached = self._lex_strong.get(corpus)
        if cached is not None:
            return cached
        stem = {"hebrew": "hbo", "greek": "grc"}.get(corpus)
        out: dict[str, str] = {}
        if stem:
            env = os.environ.get("BCV_RESOURCES_DIR")
            base = Path(env) if env else Path(__file__).resolve().parents[2] / "resources"
            path = base / "word_freq" / f"{stem}_strong.tsv"
            if path.exists():
                with path.open(encoding="utf-8") as fh:
                    next(fh, None)
                    for line in fh:
                        p = line.rstrip("\n").split("\t")
                        if len(p) == 2:
                            out[p[0]] = p[1]
        self._lex_strong[corpus] = out
        return out

    @staticmethod
    def _load_freq_file(corpus: str) -> dict[str, int] | None:
        """Load resources/word_freq/{hbo,grc}.tsv → {lex: rank}, or None if absent.
        Keep the stem mapping in sync with corpus_engine.build_freq.CORPUS_STEM."""
        stem = {"hebrew": "hbo", "greek": "grc"}.get(corpus)
        if not stem:
            return None
        env = os.environ.get("BCV_RESOURCES_DIR")
        base = Path(env) if env else Path(__file__).resolve().parents[2] / "resources"
        path = base / "word_freq" / f"{stem}.tsv"
        if not path.exists():
            return None
        rank_map: dict[str, int] = {}
        with path.open(encoding="utf-8") as fh:
            next(fh, None)  # header
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 3:
                    rank_map[parts[0]] = int(parts[2])
        return rank_map or None

    def _rank_map(self, api: Any, corpus: str) -> dict[str, int]:
        """{lex: rank} where rank 0 = most frequent lexeme. Memoized per corpus.

        Prefers the baked resources/word_freq/{hbo,grc}.tsv (cheap dict load, built
        by `python -m corpus_engine.build_freq`). Falls back to scanning the corpus
        if the file is absent — freq_lex when available (BHSA), else counting `lemma`
        occurrences (Nestle1904, which ships no frequency feature). Either path
        yields a corpus-internal rank that joins cleanly to the words /words returns.
        """
        cached = self._rank_maps.get(corpus)
        if cached is not None:
            return cached

        baked = self._load_freq_file(corpus)
        if baked is not None:
            self._rank_maps[corpus] = baked
            return baked

        feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])
        lex_feat = feat_map.get("lexeme", "lex")
        wtype = WORD_TYPE.get(corpus, "word")
        lex_obj = api.Fs(lex_feat)
        if lex_obj is None:
            self._rank_maps[corpus] = {}
            return {}
        freq_obj = api.Fs("freq_lex")
        freq_by_lex: dict[str, int] = {}
        if freq_obj is not None:
            for w in api.F.otype.s(wtype):
                lex = lex_obj.v(w)
                if not lex or lex in freq_by_lex:
                    continue
                freq = freq_obj.v(w)
                if freq is not None:
                    freq_by_lex[str(lex)] = int(freq)
        else:
            for w in api.F.otype.s(wtype):
                lex = lex_obj.v(w)
                if lex:
                    k = str(lex)
                    freq_by_lex[k] = freq_by_lex.get(k, 0) + 1
        sorted_lexemes = sorted(freq_by_lex.items(), key=lambda x: -x[1])
        rank_map = {lex: rank for rank, (lex, _) in enumerate(sorted_lexemes)}
        self._rank_maps[corpus] = rank_map
        return rank_map

    def list_words_filtered(
        self,
        corpus: str = "hebrew",
        language: str | None = None,
        pos: list[str] | None = None,
        stem: list[str] | None = None,
        tense: list[str] | None = None,
        suffix: bool | None = None,
        min_rank: int | None = None,
        max_rank: int | None = None,
        limit: int = 50,
        random_sample: bool = False,
        order: str = "pool",
        lex_filter: set | None = None,
    ) -> dict:
        """Filtered word sample across the full corpus.

        Returns {total_pool, words} where each word carries the full
        WordInfo fields plus rank, ref, clauseWords, and targetIndex.
        """
        import random as _random
        api = self._ensure_loaded(corpus)
        feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])
        wtype = WORD_TYPE.get(corpus, "word")
        clause_otype = "clause" if corpus == "hebrew" else "sentence"

        rank_map = self._rank_map(api, corpus)
        lex_strong = self._lex_strong_map(corpus)

        pos_set = set(pos) if pos else None
        stem_set = set(stem) if stem else None
        tense_set = set(tense) if tense else None

        sp_feat = feat_map.get("part_of_speech", "sp")
        vs_feat = feat_map.get("verbal_stem", "vs")
        vt_feat = feat_map.get("verbal_tense", "vt")
        lex_feat = feat_map.get("lexeme", "lex")
        lang_feat = feat_map.get("language", "language")
        prs_feat = feat_map.get("suffix_feat", "")

        sp_obj = api.Fs(sp_feat) if sp_feat else None
        vs_obj = api.Fs(vs_feat) if vs_feat else None
        vt_obj = api.Fs(vt_feat) if vt_feat else None
        lex_obj = api.Fs(lex_feat) if lex_feat else None
        lang_obj = api.Fs(lang_feat) if lang_feat else None
        prs_obj = api.Fs(prs_feat) if prs_feat else None

        matching: list[int] = []
        for w in api.F.otype.s(wtype):
            if language and lang_obj:
                lv = lang_obj.v(w)
                if not lv or str(lv) != language:
                    continue
            if pos_set and sp_obj:
                sv = sp_obj.v(w)
                if not sv or str(sv) not in pos_set:
                    continue
            if stem_set and vs_obj:
                vv = vs_obj.v(w)
                if not vv or str(vv) not in stem_set:
                    continue
            if tense_set and vt_obj:
                tv = vt_obj.v(w)
                if not tv or str(tv) not in tense_set:
                    continue
            if suffix is not None and prs_obj:
                prs_val = prs_obj.v(w)
                has_sfx = bool(prs_val) and str(prs_val) != "absent"
                if has_sfx != suffix:
                    continue
            if (min_rank is not None or max_rank is not None) and lex_obj:
                lex = lex_obj.v(w)
                r = rank_map.get(str(lex), 999999) if lex else 999999
                if min_rank is not None and r < min_rank:
                    continue
                if max_rank is not None and r > max_rank:
                    continue
            matching.append(w)

        # Restrict to lexemes that have a gloss in the requested language (keeps
        # total_pool accurate, so sampling/ordering only sees glossable words).
        if lex_filter is not None:
            matching = [w for w in matching if str(lex_obj.v(w)) in lex_filter] if lex_obj else []

        total_pool = len(matching)

        # order: how to pick `limit` words from the matching pool.
        #   frequency → the most common DISTINCT lexemes first (the standard vocab-
        #               learning order); one random example occurrence per lexeme
        #   rare      → the least common distinct lexemes first
        #   random    → a random sample of occurrences (repeat calls vary)
        #   pool      → corpus order (default)
        def _rk(node: int) -> int:
            return rank_map.get(str(lex_obj.v(node)), 10**9) if lex_obj else 10**9

        if order in ("frequency", "rare"):
            # Dedupe to distinct lexemes — else the top of a frequency sort is just the
            # same high-count word repeated. One random occurrence per lexeme = varied
            # examples; order the lexemes by rank.
            by_lex: dict[str, list[int]] = {}
            for node in matching:
                by_lex.setdefault(str(lex_obj.v(node)) if lex_obj else "", []).append(node)
            reps = [_random.choice(occ) for occ in by_lex.values()]
            reps.sort(key=_rk, reverse=(order == "rare"))
            selected = reps[:limit]
        elif order == "random" or random_sample:
            selected = _random.sample(matching, min(limit, total_pool))
        else:
            selected = matching[:limit]

        words = []
        for w in selected:
            info = self._word_info(api, w, feat_map)
            sec = api.T.sectionFromNode(w)
            book = sec[0] if len(sec) > 0 else ""
            ch = sec[1] if len(sec) > 1 else 0
            vs = sec[2] if len(sec) > 2 else 0
            ref = f"{book} {ch}:{vs}" if book else ""

            lex = lex_obj.v(w) if lex_obj else ""
            rank = rank_map.get(str(lex), 999999) if lex else 999999
            strong = lex_strong.get(str(lex)) if lex else None

            clause_words: list[str] = []
            target_index = 0
            clause_nodes = api.L.u(w, otype=clause_otype)
            if clause_nodes:
                clause_node = clause_nodes[0]
                cw_nodes = api.L.d(clause_node, otype=wtype)
                text_obj = api.Fs(feat_map.get("text", "g_word_utf8"))
                trailer_obj = api.Fs(feat_map.get("trailer", "trailer_utf8"))
                for cw in cw_nodes:
                    t = (text_obj.v(cw) or "") if text_obj else ""
                    tr = (trailer_obj.v(cw) or "") if trailer_obj else ""
                    s = str(t) + str(tr)
                    # BHSA splits prefixes (article/prep) into their own nodes; assimilated
                    # ones have no surface → empty string. Drop them so the clause renders
                    # without invisible spans; keep targetIndex aligned to the kept tokens.
                    if s == "":
                        if cw == w:
                            target_index = len(clause_words)
                        continue
                    if cw == w:
                        target_index = len(clause_words)
                    clause_words.append(s)

            words.append({
                "node": int(w),
                "lex": info.lexeme,
                "lexUtf8": info.lexeme_utf8,
                "language": info.language or (language or ""),
                "pos": info.part_of_speech,
                "stem": info.verbal_stem or "NA",
                "tense": info.verbal_tense or "NA",
                "rank": rank,
                "sfx": info.suffix,
                "gloss": info.gloss,
                "strong": strong,
                "ref": ref,
                "clauseWords": clause_words,
                "targetIndex": target_index,
            })

        return {"total_pool": total_pool, "count": len(words), "words": words}

    def get_lexeme_info(
        self,
        lexeme: str,
        corpus: str = "hebrew",
        limit: int = 50,
    ) -> dict:
        api = self._ensure_loaded(corpus)
        feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])

        lex_feat = feat_map.get("lexeme", "lex")
        gloss_feat = feat_map.get("gloss", "gloss")
        sp_feat = feat_map.get("part_of_speech", "sp")
        lex_utf8_feat = feat_map.get("lexeme_utf8", "lex_utf8")

        wtype = WORD_TYPE.get(corpus, "word")
        template = f"{wtype} {lex_feat}={lexeme}\n"
        results = list(api.S.search(template))
        corpus_count = len(results)

        first_gloss = ""
        first_sp = ""
        first_utf8 = ""
        matches = []

        for result_tuple in results[:limit]:
            w = result_tuple[0]

            if not first_gloss and gloss_feat:
                feat_obj = api.Fs(gloss_feat)
                if feat_obj:
                    g = feat_obj.v(w)
                    if g:
                        first_gloss = str(g)
            if not first_sp and sp_feat:
                feat_obj = api.Fs(sp_feat)
                if feat_obj:
                    s = feat_obj.v(w)
                    if s:
                        first_sp = str(s)
            if not first_utf8 and lex_utf8_feat:
                feat_obj = api.Fs(lex_utf8_feat)
                if feat_obj:
                    u = feat_obj.v(w)
                    if u:
                        first_utf8 = str(u)

            section = api.T.sectionFromNode(w)
            matches.append(
                {
                    "book": section[0],
                    "chapter": section[1],
                    "verse": section[2],
                    "word": self._word_info(api, w, feat_map).model_dump(),
                }
            )

        return {
            "lexeme": lexeme,
            "lexeme_utf8": first_utf8,
            "gloss": first_gloss,
            "part_of_speech": first_sp,
            "total_occurrences": corpus_count,
            "occurrences": matches,
        }

    def get_vocabulary(
        self,
        book: str,
        chapter: int,
        verse_start: int = 1,
        verse_end: int | None = None,
        corpus: str = "hebrew",
    ) -> list[dict]:
        api = self._ensure_loaded(corpus)
        feat_map = WORD_FEATURES.get(corpus, WORD_FEATURES["hebrew"])

        if verse_end is None:
            verse_end = verse_start

        wtype = WORD_TYPE.get(corpus, "word")
        lexemes: dict[str, dict] = {}

        for v in range(verse_start, verse_end + 1):
            verse_node = api.T.nodeFromSection((book, chapter, v))
            if verse_node is None:
                continue
            for w in api.L.d(verse_node, otype=wtype):
                lex_feat = feat_map.get("lexeme", "lex")
                feat_obj = api.Fs(lex_feat)
                lex = feat_obj.v(w) if feat_obj else ""
                lex = lex or ""
                if not lex or lex in lexemes:
                    if lex in lexemes:
                        lexemes[lex]["count"] += 1
                    continue

                gloss_feat = feat_map.get("gloss", "gloss")
                gloss_obj = api.Fs(gloss_feat) if gloss_feat else None
                gloss_val = gloss_obj.v(w) if gloss_obj else None

                sp_feat = feat_map.get("part_of_speech", "sp")
                sp_obj = api.Fs(sp_feat) if sp_feat else None
                sp_val = sp_obj.v(w) if sp_obj else None

                lex_utf8_feat = feat_map.get("lexeme_utf8", "lex_utf8")
                utf8_obj = api.Fs(lex_utf8_feat) if lex_utf8_feat else None
                lex_utf8_val = utf8_obj.v(w) if utf8_obj else None

                freq_obj = api.Fs("freq_lex")
                freq_val = freq_obj.v(w) if freq_obj else None

                lexemes[lex] = {
                    "lexeme": lex,
                    "lexeme_utf8": str(lex_utf8_val) if lex_utf8_val else "",
                    "gloss": str(gloss_val) if gloss_val else "",
                    "part_of_speech": str(sp_val) if sp_val else "",
                    "corpus_frequency": int(freq_val) if freq_val else 0,
                    "count": 1,
                }

        return sorted(
            lexemes.values(), key=lambda x: x["corpus_frequency"], reverse=True
        )

    def _word_info(self, api: Api, w: int, feat_map: dict[str, str]) -> WordInfo:
        def _get(canonical: str) -> str:
            tf_name = feat_map.get(canonical, "")
            if not tf_name:
                return ""
            feat_obj = api.Fs(tf_name)
            if feat_obj is None:
                return ""
            val = feat_obj.v(w)
            return str(val) if val is not None else ""

        prs_feat = feat_map.get("suffix_feat", "")
        has_suffix = False
        if prs_feat:
            prs_obj = api.Fs(prs_feat)
            if prs_obj is not None:
                prs_val = prs_obj.v(w)
                has_suffix = bool(prs_val) and str(prs_val) != "absent"

        return WordInfo(
            monad=w,
            text=_get("text"),
            trailer=_get("trailer"),
            lexeme=_get("lexeme"),
            lexeme_utf8=_get("lexeme_utf8"),
            gloss=_get("gloss"),
            part_of_speech=_get("part_of_speech"),
            gender=_get("gender"),
            number=_get("number"),
            person=_get("person"),
            state=_get("state"),
            verbal_stem=_get("verbal_stem"),
            verbal_tense=_get("verbal_tense"),
            language=_get("language"),
            suffix=has_suffix,
        )
