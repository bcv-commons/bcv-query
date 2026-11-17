"""Vector track V2: variants of the shared Hebrew-Greek space, scored on run 1's yardstick.

    python -m macula.vector_shared_space [--store macula/data/vector-store] [--vocab RUN1_DIR] [--out FILE.json]

Vocabulary and test sets are run 1's (internal-docs/clause-structure-work/m2-vectors/run1-berel-greberta: 3,800 Hebrew and 2,887
Greek lexemes; held-out Septuagint pairs with rng 13; Hebrew NT tier pairs whose Greek lexeme has no Septuagint seed).
Variants:
  A  lexeme means from the store, Procrustes on the training seed pairs (= run 1, rebuilt from the store)
  B  A with CSLS retrieval (cross-domain similarity local scaling, k = 10) in place of cosine
  C  Procrustes on occurrence pairs: a Tanakh word and the Septuagint word MACULA links it to (corpus edge `lxx`), contextual
     vectors on both sides; occurrences of held-out and test Greek lexemes are left out of training
  D  C with CSLS
  E  a linear map trained contrastively (InfoNCE) on the same occurrence pairs, with and without CSLS
No Hebrew NT link is used in training (they are the unseeded test).
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUN1 = HERE.parents[1] / "internal-docs" / "clause-structure-work" / "m2-vectors" / "run1-berel-greberta"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", type=Path, default=HERE / "data" / "vector-store")
    ap.add_argument("--vocab", type=Path, default=RUN1)
    ap.add_argument("--corpus", type=Path, default=HERE / "data" / "bridge-corpus" / "dev-builds" / "b15")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--max-pairs", type=int, default=400000)
    a = ap.parse_args()
    import pyarrow.parquet as pq
    import torch
    from macula import build_bridge_corpus as B
    api = B.load(a.corpus)
    F, E = api.F, api.E

    def lex(w):
        s = F.strong.v(w)
        if not s:
            return None
        return ("h" if F.lang.v(w) in ("hbo", "arc") else "g") + str(s).lstrip("0").rstrip("abcdefgh")

    hv = json.loads((a.vocab / "h_keys.json").read_text())["keys"]
    gv = json.loads((a.vocab / "g_keys.json").read_text())["keys"]
    hix, gix = {k: i for i, k in enumerate(hv)}, {k: i for i, k in enumerate(gv)}
    lk = json.loads((a.store / "lexemes.json").read_text())["keys"]
    LX = np.load(a.store / "lexemes.npy")
    li = {k: i for i, k in enumerate(lk)}
    mean = lambda keys: np.stack([LX[li[k]] for k in keys]).astype(np.float32)
    Hm, Gm = mean(hv), mean(gv)
    hmu, gmu = Hm.mean(0), Gm.mean(0)

    def norm(X):
        return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)

    H, G = norm(Hm - hmu), norm(Gm - gmu)

    def pairs(name):
        ps = []
        for h in F.otype.s("lexeme"):
            for g, n in getattr(E, name).f(h):
                ws = [w for w in E.oslots.s(g) if F.strong.v(w)][:1]
                hs = [w for w in E.oslots.s(h) if F.strong.v(w)][:1]
                if ws and hs:
                    ps.append((lex(hs[0]), lex(ws[0])))
        return [(x, y) for x, y in ps if x in hix and y in gix]

    seed = pairs("tier_macula")
    rng = np.random.default_rng(13)
    idx = rng.permutation(len(seed))
    cut = int(0.8 * len(seed))
    train = [seed[i] for i in idx[:cut]]
    held = [seed[i] for i in idx[cut:]]
    trg = {g for _, g in train}
    held = [p for p in held if p[1] not in trg]
    seedg = {g for _, g in seed}
    tests = {"held-out Septuagint": held,
             "Salkinson, no Septuagint seed": [p for p in pairs("tier_heb_scg") if p[1] not in seedg],
             "Delitzsch, no Septuagint seed": [p for p in pairs("tier_heb_mod") if p[1] not in seedg]}
    banned = {g for ps in tests.values() for _, g in ps}

    def csls(Q, T, k=10):
        S = Q @ T.T
        rq = np.sort(S, axis=1)[:, -k:].mean(1)
        rt = np.sort((T @ Q.T) if len(Q) < 4000 else S.T, axis=1)[:, -k:].mean(1)
        return 2 * S - rq[:, None] - rt[None, :]

    def score(Gmapped, use_csls, train_only=False):
        out = {}
        for name, ps in tests.items():
            gold = collections.defaultdict(set)
            for h, g in ps:
                gold[g].add(h)
            gs = list(gold)
            if use_csls:
                allq = norm(Gmapped)
                S = csls(allq, H)[[gix[g] for g in gs]]
            else:
                S = norm(Gmapped[[gix[g] for g in gs]]) @ H.T
            hit = collections.Counter()
            for i, g in enumerate(gs):
                top = np.argsort(-S[i])[:10]
                for k in (1, 3, 10):
                    hit[k] += bool({hv[j] for j in top[:k]} & gold[g])
            out[name] = {"n": len(gs), **{f"top{k}": round(hit[k] / len(gs), 3) for k in (1, 3, 10)}}
        return out

    def procrustes(A, Bm):
        u, _, vt = np.linalg.svd(A.T @ Bm)
        return u @ vt

    res = {}
    # A/B: lexeme Procrustes on training pairs (held-out test uses train; unseeded tests use all seed pairs, as in run 1)
    Wt = procrustes(G[[gix[g] for _, g in train]], H[[hix[h] for h, _ in train]])
    Ws = procrustes(G[[gix[g] for _, g in seed]], H[[hix[h] for h, _ in seed]])

    def both(Wt_, Ws_, c):
        r1 = score(G @ Wt_, c)
        r2 = score(G @ Ws_, c)
        return {"held-out Septuagint": r1["held-out Septuagint"], "Salkinson, no Septuagint seed": r2["Salkinson, no Septuagint seed"],
                "Delitzsch, no Septuagint seed": r2["Delitzsch, no Septuagint seed"]}

    res["A lexeme Procrustes"] = both(Wt, Ws, False)
    res["B lexeme Procrustes + CSLS"] = both(Wt, Ws, True)
    print(json.dumps(res, indent=1), flush=True)

    # occurrence pairs from the lxx edge
    rows = {}
    for t in ("tanakh", "septuagint"):
        nodes = pq.read_table(a.store / f"{t}.parquet", columns=["node"]).column("node").to_pylist()
        rows[t] = ({n: i for i, n in enumerate(nodes)}, np.load(a.store / f"{t}.npy", mmap_mode="r"))
    hr, HX = rows["tanakh"]
    gr, GX = rows["septuagint"]
    occ = []
    held_g = {g for _, g in tests["held-out Septuagint"]}
    for w in hr:
        kh = lex(w)
        if kh not in hix:
            continue
        for (g, label) in E.lxx.f(w) or ():
            g = int(g)
            kg = lex(g)
            if kg in gix and kg not in banned and g in gr:
                occ.append((hr[w], gr[g], kg in held_g))
    rng.shuffle(occ)
    occ = occ[: a.max_pairs]
    print("occurrence pairs", len(occ), flush=True)
    A_ = np.asarray(GX[[g for _, g, _ in occ]], dtype=np.float32) - gmu
    B_ = np.asarray(HX[[h for h, _, _ in occ]], dtype=np.float32) - hmu
    A_, B_ = norm(A_), norm(B_)
    Wo = procrustes(A_, B_)
    res["C occurrence Procrustes"] = {k: v for k, v in score(G @ Wo, False).items()}
    res["D occurrence Procrustes + CSLS"] = {k: v for k, v in score(G @ Wo, True).items()}
    print(json.dumps({k: res[k] for k in list(res)[2:]}, indent=1), flush=True)

    # E: contrastive linear map, initialised at Wo
    dev = "cuda"
    At, Bt = torch.tensor(A_, device=dev), torch.tensor(B_, device=dev)
    W = torch.nn.Parameter(torch.tensor(Wo, device=dev))
    opt = torch.optim.Adam([W], lr=1e-4)
    tau = 0.05
    for ep in range(3):
        perm = torch.randperm(len(At), device=dev)
        for s in range(0, len(At), 4096):
            b = perm[s:s + 4096]
            q = torch.nn.functional.normalize(At[b] @ W, dim=1)
            k = Bt[b]
            logits = q @ k.T / tau
            lab = torch.arange(len(b), device=dev)
            loss = (torch.nn.functional.cross_entropy(logits, lab) + torch.nn.functional.cross_entropy(logits.T, lab)) / 2
            opt.zero_grad()
            loss.backward()
            opt.step()
        print("E epoch", ep, float(loss.detach()), flush=True)
    We = W.detach().cpu().numpy()
    res["E contrastive linear"] = score(G @ We, False)
    res["E contrastive linear + CSLS"] = score(G @ We, True)
    print(json.dumps(res["E contrastive linear + CSLS"], indent=1), flush=True)
    if a.out:
        a.out.write_text(json.dumps({"occurrence pairs": len(occ), "variants": res}, indent=1))


if __name__ == "__main__":
    main()
