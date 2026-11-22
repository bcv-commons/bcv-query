"""D4 (SPEC 1.0, section 6): relmap, a D3 label -> a Universal Dependencies relation (universal names, no subtypes).

The table is written here by hand, as the specification asks ("written as tables inside the builder"); the builder
only looks labels up. How a row was chosen: a label names one place of one MACULA rule (or a role code), so it is
mapped to the UD relation that fits the largest group of the words that carry it, when that group is more than half of them (their class, case and lemma were counted in
stage 03, see reports/03-heads.md). Where no relation fits more than half of the label's words, the row says `dep`,
UD's own "unspecified dependency", rather than a guess. Every label that covers at least 0.1% of a language's words is here;
labels under that share and not here are `none`. Labels between clauses (`run:<place>`, `ClCl:1`, `ClCl2:0`) are not
decided by class: a clause in a run is `conj`, a clause beside a clause with no conjunction node is `parataxis`.

Keys: "all" holds the rows of every language; a language key overrides a row for that language only.
"""

_ROLES = {
    "s": "nsubj",
    "o": "obj",
    "o2": "obj",       # MACULA's second object; double accusatives and secondary predicates alike
    "io": "iobj",
    "p": "xcomp",      # a predicate that is a dependent (rare: hbo 1, grc 58)
    "vc": "cop",
    "pp": "obl",       # Hebrew and Aramaic prepositional constituent
    "adv": "advmod",   # Hebrew and Aramaic: adverbs are the largest group (hbo 7,268 of 12,111)
    "v": "dep",        # a verb constituent that is not its clause's head: participles and verbs of several kinds
}

_RULES = {
    # nominal phrases
    "NPofNP:1": "nmod", "ofNPNP:0": "nmod", "NpPp:1": "nmod",
    "Np-Appos:1": "appos",
    "NpAdjp:1": "amod", "AdjpNp:0": "amod", "NPDetAdj:1": "amod",
    "QuanNP:0": "det", "All-NP:0": "det", "DetNP:0": "det", "DetCL:0": "det", "DetAdj:0": "det",
    "NP-Demo:1": "det", "Demo-NP:0": "det", "PronNP:0": "det",
    "NumpNP:0": "nummod", "NpNump:1": "nummod", "NumpNump:0": "compound",
    "NpRelp:1": "acl", "NpCL:1": "acl", "NP-CL:1": "acl",
    "AdvpNp:0": "advmod", "PpAdvp:1": "advmod",
    "c:1": "flat", "c:2": "flat", "c:3": "flat",
    "2Np:0": "dep", "2Pp:1": "dep", "PpPp:0": "dep",
    # markers
    "PrepNp:0": "case", "OmpNP:0": "case", "relNp:0": "case",
    "relCL:0": "mark", "PrepCL:0": "mark", "ppCL:0": "mark", "cjpCLx:0": "mark",
    "sub-CL:0": "mark", "that-VP:0": "mark",
    "Conj-CL:0": "cc",
    "cjpNp:0": "advmod", "PtclCL:0": "advmod",
    # verbs
    "BeVerb:0": "aux", "vpVp2V2:0": "aux", "Vpvp2V1:1": "aux",
    # clauses side by side without a conjunction node at that level
    "ClCl:1": "parataxis", "ClCl2:0": "parataxis",
    # coordination: the conjunction is cc, the other conjuncts conj
    "NpaNp:1": "cc", "NpaNp:2": "conj",
    "CLaCL:1": "cc", "CLaCL:2": "conj",
    "CLandCL2:0": "conj", "CLandCL2:1": "cc",
    "PPandPP:0": "conj", "PPandPP:1": "cc",
    "NumpAndNump:0": "conj", "NumpAndNump:1": "cc",
    "AdjpaAdjp:0": "conj", "AdjpaAdjp:1": "cc",
    "VPandVP:0": "conj", "VPandVP:1": "cc",
    "Conj2VP:1": "cc", "Conj2VP:2": "conj",
    "aCLaCL:0": "cc", "aCLaCL:2": "cc", "aCLaCL:3": "conj",
    "notCLbutCL2CL:0": "advmod", "notCLbutCL2CL:1": "conj", "notCLbutCL2CL:2": "cc",
    "NP3NP:1": "conj", "NP3NP:2": "cc", "NP3NP:3": "conj",
}
# Conj<N>Np, Conj<N>CL, Conj<N>Pp: the conjuncts stand at even places, the conjunctions at odd places
for _n in range(3, 8):
    for _r in (f"Conj{_n}Np", f"Conj{_n}CL", f"Conj{_n}Pp"):
        for _p in range(0, 2 * _n - 1):
            _RULES[f"{_r}:{_p}"] = "cc" if _p % 2 else "conj"
# Hebrew and Aramaic runs (a node without Rule): the first child is the head, and the clauses after it and the
# conjunctions between them all depend on it; the clauses are the largest group at every place (run:2 cj 2,513 of
# 10,516 words), so the runs are `conj`
for _p in range(1, 40):
    _RULES[f"run:{_p}"] = "conj"

RELMAP = {
    "all": {**_ROLES, **_RULES, "root": "root"},
    # Greek role adv: no class is half of its words (noun 7,514, verb 5,094, adv 4,455, pron 2,753 of 21,306):
    # prepositional and case phrases, participle clauses, negators and adverbs alike
    # Greek role aux: vocatives are more than half of its words (532 of 967; the rest ἰδού and others)
    "grc": {"adv": "dep", "aux": "vocative"},
}
