# Reviewing the heb_scg alignment: bridge, Jev, Claude, each decision attributed

The Greek ↔ Salkinson–Ginsburg alignment (bcv-commons/alignments-by-id v1.1, `n1904/h/heb/heb_scg`) is the hub that replaces the
BSB English: it ties the Greek NT to Hebrew words, the words of the Tanakh. This page designs its review: three filters, each
cheaper than the next is careful, so that only a small pool reaches the last one, and every link carries where its final form
came from. The hand check that motivates it is in `lab/rules/RUN.md` (2026-10-31): 86% of content words right; the errors sit in
half of the words, which the lexeme bridge finds.

## The stages

```
 published layer (aligner chain + Jev v4, lexeme-aligner)        64,723 content Greek words
        │
 1. BRIDGE (free, code) ── kept link agrees with the bridge ───► accepted   ~33,900   (0 errors in 40 checked)
        │ the rest: kept-disagree, edited, "not rendered", lexeme unknown to the bridge   ~30,800 (16% wrong)
        ▼
 2. JEV CHECK (paid, one judgment per word) ── confident ───────► decided    (threshold set on the reference set)
        │ uncertain, or Jev disagrees with a link the bridge supports
        ▼
 3. CLAUDE REVIEW (no API cost; sessions) ── judged with a note ─► decided
        │
 4. SPOT CHECK by a person, a fixed sample from every source ──► measured precision per source
```

### 1. Bridge triage (code; `scg_check.groups`)

A kept link whose Hebrew word is a bridge rendering of the Greek lexeme is accepted as published. Everything else goes on. The
bridge never changes a link itself: its candidate was right in 24 of 39 wrong links but would also have mislinked every correct
"not rendered" word of its group.

### 2. Jev check (TypeSafe; one Choice per Greek word)

- **State:** the Greek verse with the word marked, its lemma and Strong's number; the Hebrew verse with numbered words and the
  parts of each word (prefixes, stem, suffixes) as hebrew-nt-analysis gives them; no English glosses.
- **Options:** the current link; every unlinked content word or part of the verse; the bridge's renderings marked as such
  (evidence, not an answer); "not rendered in this verse".
- **Answer:** the chosen option and its probability. Decided when the probability is at least the threshold for that kind of
  answer (keep, move, add, drop); otherwise passed on. Also passed on: Jev drops or moves a link the bridge supports.
- **Thresholds**, one per kind of decision, are set on the reference words of the review pool (240 of the 280 judged blind;
  K+ is the bridge's), first on half A and tested on half B, then fixed from all 240 (2026-10-31, `calibration.json`; under
  rules v1: keep 0.5 (134/135 right), move 0.5 (17/17), add 0.77 (26/27), not rendered 0.8 (14/14); rules v2 below). On half B the A thresholds gave 97.3%
  (group-weighted) with 95% of the words decided; add and not rendered were the kinds that missed, so their thresholds went up.
  Target: at least 95% right among the decided, "right" meaning agreement with Claude's blind judgment.
- **Running check:** because the final thresholds were set on all reference words, the held-out test is a fresh blind sample
  of Jev's decisions (30 per kind, `scg_review.py spot`), judged by Claude without seeing Jev's answer.
- Version 1 decides which word renders the Greek word. Trimming a link to the right part (a suffix that renders μου, a ו that
  renders δέ) is a second question, version 2, once version 1 is measured.

### 3. Claude review (the final pool)

The uncertain words, in batches of 20, each shown as in the hand check (Greek verse, Hebrew verse with numbered words, the
current link, Jev's top two options with probabilities, the bridge's renderings). Judged by the rules of the hand check
(`private/rules/bridge/scg_check/judgments.tsv`, header and round 1): the decision, the Hebrew word or part, a one-line reason.
Batches are logged with the model, the date and the rule version. The pool is ordered by expected error (the "not rendered"
groups first), so a partial pass already removes most errors.

### 4. Spot check by a person

A fixed random sample from each decision source (accepted by the bridge, decided by Jev, decided by Claude), read by someone who
reads Hebrew and Greek. It measures each source's precision, and is the place to tighten a threshold or a rule.

## The record: a correction layer, not an edit

The published layer is never changed. The review writes a layer on top, one line per content Greek word (an illustration;
the id and the figures are made up):

```json
{"gid": "n41005033012", "ref": "MRK 5:33",
 "before": {"link": ["11.1", "12.0", "12.1", "12.2"], "class": "kept"},
 "after":  {"link": ["11.1"], "status": "changed"}, "how": "lexical",
 "decided_by": "claude-review-v1",
 "evidence": {"bridge": [11], "jev": {"choice": "11", "p": 0.62, "second": ["11+12", 0.31]}},
 "note": "ותפל; לפניו renders αὐτῷ",
 "rules": "scg-review rules v2", "model": "claude-opus-5-5", "date": "2026-11-01"}
```

`decided_by` is one of: `published` (aligner chain + Jev v4, accepted by the bridge), `jev-check-v1`, `claude-review-v1`,
`person:<initials>` (spot check overrides). Everything a later reviewer needs is on the line: what it was, what it became, who
decided, on which evidence. A new threshold or rule reruns one stage and changes only its own lines; the layer can go back to
lexeme-aligner as a correction to their dataset, on the user's go.

## Costs and sizes

- Stage 1: free, done.
- Stage 2: about 30,800 judgments, about 1,800 input tokens each. The calibration run on the 280 reference words cost $0.02;
  the whole pool is about $2.30 (capped at $3).
- Stage 3: the pool size follows from the threshold. Claude judged about 400 words in one session; a pool of a few thousand is
  several sessions, worked in error order.
- Stage 4: about 30 words per source.

## Rules v2: link what carries the meaning (2026-10-31)

Settled by what helps the draft reviews: an aligned draft flags a Greek word nothing links to, and those flags caught real gaps
only 6-13% of the time (pipeline.md), partly because the hub left light verbs and auxiliaries unlinked by design. So:

- **Linked, `lexical`:** the Hebrew word is a translation of the Greek word.
- **Linked, `phrase`:** the Greek word is part of a unit one Hebrew word carries: a light verb (συμβούλιον ἔλαβον = ויועצו,
  πληγὰς ἐπιθέντες = הכהו), a periphrastic ἦν (ἦν προσδοκῶν = הוחילו), possession by ל (ἔχητε = לכם), a word gapped in
  the Hebrew and carried by the one in the parallel clause.
- **Linked, `free`:** the Hebrew rewords it and a word carries its meaning (οὐκ ἔστιν ἐκ πίστεως = לא אמונה תבקש).
- **Not rendered:** no Hebrew word carries it: the copula of a nominal clause, an omission, the clause in another verse.

A reviewer then sees where each Greek word went, and "not rendered" in the hub marks the words a draft may also leave out, so
draft flags can skip them. Lexicon learners (the bridge, rule tables) should read only `lexical` links. Claude's judgments carry
the mark in the note. Jev's decided links were asked the mark too (one Choice each, $1.01 for 26,764): its answer is kept at
p >= 0.7 (237/250 against Claude's marks; 55-62% below), else the link is marked `uncertain` and stays out of the lexicon learners.
The layer's `how` field holds the mark for every linked word (published, bridge-agreed links: `lexical`).

Effect on stage 2: Jev's "not rendered" answers fit v2 worse (22/30 in the spot check), so they always go to Claude; "add"
fits better (reference 43/43 at 0.5; blind band check 27/30 at 0.50-0.77, all three misses below 0.55), so add = 0.55.
Thresholds now: keep 0.5, move 0.5, add 0.55, not rendered never.

## Open

- The parts question (version 2).
