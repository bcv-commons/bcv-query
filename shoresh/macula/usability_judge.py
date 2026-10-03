#!/usr/bin/env python3
"""Run LLM judges over the frozen usability items, and report the scorecard's judged measures.

Judges (model overridable by env):
  claude   JUDGE_CLAUDE_MODEL, default claude-sonnet-5-5, via the official anthropic SDK, adaptive
           thinking at effort "low". Not Haiku: Haiku wrote part of the CC0 pack (prior-tier edges, pair
           verification), which would make it partly circular for P1/P2.
  claude-cli  JUDGE_CLAUDE_CLI_MODEL, default claude-sonnet-5-5, through Claude Code's headless mode
           (`claude -p`), which runs on the user's Claude subscription instead of API credit. Same model
           and effort as `claude`. ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are removed from the subprocess
           environment (otherwise it would bill the API), and it runs from an empty temp directory with a
           short system prompt, so no project CLAUDE.md or memory reaches the judge.
  openai   JUDGE_OPENAI_MODEL, default gpt-5.4-mini (plain HTTP).
  groq     JUDGE_GROQ_MODEL, default openai/gpt-oss-120b (open weights, hosted by Groq). Stand-in second
           judge (used while the OpenAI account had no credits); optional third vote.
Keys come from the environment or shoresh/.env and bcv-RAG/.env. The local DictaLM is not used: it failed
calibration as a judge (internal-docs/phase-c-instrument-calibration-plan.md).

Judges never see the answer key: only an item's id and its words/verse/options are sent. Results are
appended per item (resumable) to data/usability/judgments/<judge>--<model>/<variant>/<task>/<file>.jsonl,
so results from different models never mix.

Variants: `served` shows labels exactly as a client sees them; `lemma` strips the English reading aid
from exemplar labels ("אֹהֶל · tent" -> "אֹהֶל"), so labelfit can be read Hebrew-only.

  cd shoresh && .venv/bin/python3 -m macula.usability_judge --gold                       # judge gate
  cd shoresh && .venv/bin/python3 -m macula.usability_judge --run --split dev --providers P0 PR-P0
  cd shoresh && .venv/bin/python3 -m macula.usability_judge --report --split dev
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from macula.usability_items import ITEMS, PROVIDERS, SEEDS

HERE = Path(__file__).resolve().parent
JUDGMENTS = HERE / "data" / "usability" / "judgments"
RESULTS = HERE / "data" / "usability" / "scorecard"
BATCH = 20
WORKERS = 6
JUDGES = ("claude-cli", "openai")
MODELS = {"claude": os.environ.get("JUDGE_CLAUDE_MODEL", "claude-sonnet-5-5"),
          "claude-cli": os.environ.get("JUDGE_CLAUDE_CLI_MODEL", "claude-sonnet-5-5"),
          "openai": os.environ.get("JUDGE_OPENAI_MODEL", "gpt-5.4-mini"),
          "groq": os.environ.get("JUDGE_GROQ_MODEL", "openai/gpt-oss-120b")}
WORKERS_FOR = {"groq": 2, "claude-cli": 4}   # Groq per-minute limits; subscription rate limits

PROMPTS = {
    "intrusion": (
        "You are an expert in Biblical Hebrew vocabulary. Each item below lists Biblical Hebrew words "
        "(dictionary forms). All but one of them belong together by meaning; exactly one is the odd one "
        "out. For every item, give the number of the odd one out.\n"
        "Reply with JSON only, no prose: a list of objects {\"id\": <item id>, \"choice\": <number>}.\n\n"
        "Items:\n"),
    "labelfit": (
        "You are an expert in Biblical Hebrew. Each item below is a verse of the Hebrew Bible with one word "
        "marked like ⟦this⟧, followed by four candidate labels for that word's meaning. A label is either "
        "a short category name or a Hebrew word (optionally followed by an English gloss) that stands for a "
        "group of related words. For every item, choose the label that best fits the meaning of the marked "
        "word in this verse.\n"
        "Reply with JSON only, no prose: a list of objects {\"id\": <item id>, \"choice\": <number>}.\n\n"
        "Items:\n"),
}


def judge_dir(judge: str) -> Path:
    return JUDGMENTS / f"{judge}--{MODELS[judge].replace('/', '_')}"


# ---------- keys ----------

def _load_env() -> None:
    for env in (HERE.parent / ".env", HERE.parents[1] / "bcv-RAG" / ".env"):
        if not env.exists():
            continue
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if not os.environ.get(k):
                    os.environ[k] = v.strip().strip('"').strip("'")


# ---------- rendering ----------

def lemma_only(label: str) -> str:
    return label.split(" · ", 1)[0]


def render(item: dict, variant: str) -> dict:
    if item["task"] == "intrusion":
        return {"id": item["id"], "words": {str(i + 1): w["lemma"] for i, w in enumerate(item["words"])}}
    opts = [lemma_only(o) if variant == "lemma" else o for o in item["options"]]
    return {"id": item["id"], "verse": item["verse"], "labels": {str(i + 1): o for i, o in enumerate(opts)}}


# ---------- API calls ----------

def _post(url: str, body: dict, headers: dict, tries: int = 6) -> dict | None:
    data = json.dumps(body).encode()
    for attempt in range(tries):
        # Groq's Cloudflare front returns 403 / error 1010 for urllib's default User-Agent.
        req = urllib.request.Request(url, data=data, headers={
            "content-type": "application/json", "user-agent": "bcv-query-usability/1.0", **headers})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"[judge] HTTP {e.code} (try {attempt + 1}): {detail[:200]}", file=sys.stderr)
            if e.code in (400, 401, 403, 404) or "insufficient_quota" in detail:
                return None
            retry_after = e.headers.get("retry-after") if e.headers else None
            if retry_after:
                try:
                    time.sleep(min(float(retry_after), 60))
                    continue
                except ValueError:
                    pass
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            print(f"[judge] network error (try {attempt + 1}): {e}", file=sys.stderr)
        time.sleep(min(2 ** attempt, 30))
    return None


_claude_client = None


def call_claude(prompt: str) -> tuple[str, int, int]:
    """Adaptive thinking stays on (the model default); effort "low" keeps it short. max_tokens leaves room
    for thinking plus the JSON answer: at 4000 the judge spent the whole budget thinking and returned no
    text."""
    import anthropic

    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(max_retries=6, timeout=300.0)
    try:
        resp = _claude_client.messages.create(
            model=MODELS["claude"], max_tokens=16000, output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}])
    except (anthropic.BadRequestError, anthropic.AuthenticationError, anthropic.PermissionDeniedError,
            anthropic.NotFoundError) as e:
        print(f"[judge] claude request rejected: {e}", file=sys.stderr)
        return "", 0, 0
    except anthropic.APIStatusError as e:
        print(f"[judge] claude HTTP {e.status_code} after retries: {e.message}", file=sys.stderr)
        return "", 0, 0
    except anthropic.APIConnectionError as e:
        print(f"[judge] claude connection error after retries: {e}", file=sys.stderr)
        return "", 0, 0
    if resp.stop_reason in ("max_tokens", "refusal"):
        print(f"[judge] claude stop_reason={resp.stop_reason}", file=sys.stderr)
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, resp.usage.input_tokens, resp.usage.output_tokens


_cli_cwd: str | None = None


def call_claude_cli(prompt: str, tries: int = 4) -> tuple[str, int, int]:
    import subprocess
    import tempfile

    global _cli_cwd
    if _cli_cwd is None:
        _cli_cwd = tempfile.mkdtemp(prefix="usability-judge-")
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    cmd = ["claude", "-p", "--model", MODELS["claude-cli"], "--effort", "low", "--no-session-persistence",
           "--output-format", "json", "--system-prompt",
           "You are a careful expert judge. Answer exactly in the requested format.", "--tools", ""]
    for attempt in range(tries):
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env,
                                  cwd=_cli_cwd, timeout=600)
            out = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            print(f"[judge] claude-cli failed (try {attempt + 1}): {e}", file=sys.stderr)
            time.sleep(min(2 ** attempt * 5, 60))
            continue
        if out.get("is_error"):
            print(f"[judge] claude-cli error (try {attempt + 1}): {str(out.get('result'))[:200]}", file=sys.stderr)
            if "login" in str(out.get("result", "")).lower():
                return "", 0, 0
            time.sleep(min(2 ** attempt * 5, 60))
            continue
        u = out.get("usage", {})
        tok_in = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
        return out.get("result") or "", tok_in, u.get("output_tokens", 0)
    return "", 0, 0


def call_judge(judge: str, prompt: str) -> tuple[str, int, int]:
    if judge == "claude":
        return call_claude(prompt)
    if judge == "claude-cli":
        return call_claude_cli(prompt)
    if judge == "groq":
        url, key = "https://api.groq.com/openai/v1/chat/completions", os.environ["GROQ_API_KEY"].strip()
    else:
        url, key = "https://api.openai.com/v1/chat/completions", os.environ["OPENAI_API_KEY"].strip()
    resp = _post(url, {"model": MODELS[judge], "reasoning_effort": "low", "max_completion_tokens": 8000,
                       "messages": [{"role": "user", "content": prompt}]},
                 {"Authorization": f"Bearer {key}"})
    if not resp:
        return "", 0, 0
    text = resp["choices"][0]["message"].get("content") or ""
    u = resp.get("usage", {})
    return text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def parse(text: str, items: list[dict]) -> dict[str, int]:
    """id -> 0-based choice, keeping only in-range answers for ids that were asked."""
    n_opts = {it["id"]: len(it["words"]) if it["task"] == "intrusion" else len(it["options"]) for it in items}
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return {}
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out = {}
    for rec in arr if isinstance(arr, list) else []:
        try:
            iid, choice = rec["id"], int(rec["choice"])
        except (KeyError, TypeError, ValueError):
            continue
        if iid in n_opts and 1 <= choice <= n_opts[iid]:
            out[iid] = choice - 1
    return out


# ---------- running ----------

def judge_file(judge: str, variant: str, items: list[dict], out_path: Path) -> tuple[int, int, int]:
    done = set()
    if out_path.exists():
        done = {json.loads(line)["id"] for line in out_path.read_text(encoding="utf-8").splitlines() if line}
    todo = [it for it in items if it["id"] not in done]
    if not todo:
        return 0, 0, 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    task = todo[0]["task"]
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    itok = otok = n = 0

    def run(batch: list[dict]):
        prompt = PROMPTS[task] + json.dumps([render(it, variant) for it in batch], ensure_ascii=False, indent=1)
        text, i, o = call_judge(judge, prompt)
        return batch, parse(text, batch), i, o

    with concurrent.futures.ThreadPoolExecutor(WORKERS_FOR.get(judge, WORKERS)) as pool, out_path.open("a", encoding="utf-8") as fh:
        for batch, got, i, o in pool.map(run, batches):
            itok += i
            otok += o
            for it in batch:
                if it["id"] in got:
                    fh.write(json.dumps({"id": it["id"], "choice": got[it["id"]]}) + "\n")
                    n += 1
            fh.flush()
    return n, itok, otok


def load_items(rel: str, split: str | None) -> list[dict]:
    path = ITEMS / rel
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [it for it in items if split is None or it["split"] == split]


def load_choices(judge: str, variant: str, rel: str) -> dict[str, int]:
    path = judge_dir(judge) / variant / rel
    if not path.exists():
        return {}
    return {r["id"]: r["choice"] for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r}


# ---------- scoring ----------

def score(items: list[dict], choices: dict[str, int]) -> dict | None:
    judged = [it for it in items if it["id"] in choices]
    if not judged:
        return None
    acc = sum(choices[it["id"]] == it["answer"] for it in judged) / len(judged)
    chance = statistics.mean(it["chance"] for it in judged)
    rec = {"n": len(judged), "acc": acc, "chance": chance, "norm": (acc - chance) / (1 - chance)}
    if judged[0]["task"] == "intrusion":
        w = sum(it.get("weight", 1) for it in judged)
        rec["acc_token_weighted"] = sum(it.get("weight", 1) * (choices[it["id"]] == it["answer"])
                                        for it in judged) / w
    else:
        shared = [it for it in judged if it.get("shared")]
        if shared:
            rec["acc_shared"] = sum(choices[it["id"]] == it["answer"] for it in shared) / len(shared)
            rec["n_shared"] = len(shared)
    return rec


def kappa(items: list[dict], a: dict[str, int], b: dict[str, int]) -> float | None:
    both = [it for it in items if it["id"] in a and it["id"] in b]
    if len(both) < 10:
        return None
    po = sum(a[it["id"]] == b[it["id"]] for it in both) / len(both)
    ca = collections.Counter(a[it["id"]] for it in both)
    cb = collections.Counter(b[it["id"]] for it in both)
    pe = sum(ca[k] * cb[k] for k in ca) / (len(both) ** 2)
    return (po - pe) / (1 - pe) if pe < 1 else None


def report(split: str, variants: list[str], providers: list[str], judges: list[str]) -> dict:
    out: dict = {"split": split, "rows": []}
    for task in ("intrusion", "labelfit"):
        for variant in variants:
            if task == "intrusion" and variant != "served":
                continue
            p0_norm: dict[str, float] = {}
            for provider in providers:
                for judge in judges:
                    per_seed = []
                    for seed in SEEDS:
                        rel = f"{task}/{provider}_s{seed}.jsonl"
                        if not (ITEMS / rel).exists():
                            continue
                        rec = score(load_items(rel, split), load_choices(judge, variant, rel))
                        if rec:
                            per_seed.append(rec)
                    if not per_seed:
                        continue
                    norms = [r["norm"] for r in per_seed]
                    row = {"task": task, "variant": variant, "provider": provider, "judge": judge,
                           "seeds": len(per_seed), "n": sum(r["n"] for r in per_seed),
                           "acc": statistics.mean(r["acc"] for r in per_seed),
                           "chance": statistics.mean(r["chance"] for r in per_seed),
                           "norm": statistics.mean(norms),
                           "norm_sd": statistics.stdev(norms) if len(norms) > 1 else 0.0}
                    for k in ("acc_token_weighted", "acc_shared"):
                        vals = [r[k] for r in per_seed if k in r]
                        if vals:
                            row[k] = statistics.mean(vals)
                    if provider == "P0":
                        p0_norm[judge] = row["norm"]
                    if judge in p0_norm and p0_norm[judge] > 0:
                        row["retention"] = row["norm"] / p0_norm[judge]
                    out["rows"].append(row)
                if len(judges) < 2:
                    continue
                kap = []
                for seed in SEEDS:
                    rel = f"{task}/{provider}_s{seed}.jsonl"
                    if (ITEMS / rel).exists():
                        k = kappa(load_items(rel, split), load_choices(judges[0], variant, rel),
                                  load_choices(judges[1], variant, rel))
                        if k is not None:
                            kap.append(k)
                if kap:
                    out.setdefault("judge_kappa", {})[f"{task}/{variant}/{provider}"] = statistics.mean(kap)
    return out


LOCK = HERE / "data" / "usability" / "test_lock.json"
LEDGER = HERE / "data" / "usability" / "test_runs.jsonl"


def _items_manifest_sha() -> str:
    import hashlib
    return hashlib.sha256((ITEMS / "manifest.json").read_bytes()).hexdigest()


def _item_files() -> dict[str, str]:
    return json.loads((ITEMS / "manifest.json").read_text(encoding="utf-8"))["files"]


def lock_test(note: str) -> None:
    """Freeze the current item files. Later item files (new candidates) can be added; locked ones may
    never change."""
    if LOCK.exists():
        sys.exit(f"test split already locked: {LOCK}")
    rec = {"locked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "items_manifest_sha256": _items_manifest_sha(),
           "files": _item_files(), "note": note}
    LOCK.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[lock] {LOCK}: {rec['items_manifest_sha256'][:12]}")


def check_test_lock(args) -> None:
    """Test items may only be judged against the locked item set; every test run goes into the ledger."""
    if not LOCK.exists():
        sys.exit("test split is not locked; run --lock-test first")
    locked = json.loads(LOCK.read_text(encoding="utf-8"))["files"]
    current = _item_files()
    changed = [f for f, h in locked.items() if current.get(f) != h]
    if changed:
        sys.exit(f"locked item files changed since the test split was locked: {changed[:5]}")
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "judges": args.judges,
                             "models": {j: MODELS[j] for j in args.judges}, "providers": args.providers,
                             "tasks": args.tasks, "variants": args.variants, "seeds": args.seeds}) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", action="store_true", help="run both judges on the gold items and report the gate")
    ap.add_argument("--lock-test", metavar="NOTE", help="freeze the test split's item hashes (once)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--providers", nargs="*", default=list(PROVIDERS))
    ap.add_argument("--tasks", nargs="*", default=["intrusion", "labelfit"])
    ap.add_argument("--judges", nargs="*", default=list(JUDGES), choices=sorted(MODELS))
    ap.add_argument("--variants", nargs="*", default=["served"])
    ap.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    args = ap.parse_args()
    _load_env()

    if args.gold:
        items = load_items("gold.jsonl", None)
        ok = True
        for judge in args.judges:
            n, i, o = judge_file(judge, "served", items, judge_dir(judge) / "served" / "gold.jsonl")
            ch = load_choices(judge, "served", "gold.jsonl")
            for task in ("intrusion", "labelfit"):
                rec = score([it for it in items if it["task"] == task], ch)
                acc = rec["acc"] if rec else 0.0
                ok &= acc >= 0.9
                print(f"[gold] {judge:7} {MODELS[judge]:18} {task:10} acc={acc:.3f} "
                      f"n={rec['n'] if rec else 0} {'PASS' if acc >= 0.9 else 'FAIL'}")
                for it in items:
                    if it["task"] == task and it["id"] in ch and ch[it["id"]] != it["answer"]:
                        print(f"        miss {it['id']}")
            print(f"[gold] {judge} tokens in={i} out={o}")
        return 0 if ok else 1

    if args.lock_test:
        lock_test(args.lock_test)
        return 0

    if args.run:
        if args.split == "test":
            check_test_lock(args)
        for judge in args.judges:
            for variant in args.variants:
                for task in args.tasks:
                    for provider in args.providers:
                        for seed in args.seeds:
                            rel = f"{task}/{provider}_s{seed}.jsonl"
                            if not (ITEMS / rel).exists() or (task == "intrusion" and variant != "served"):
                                continue
                            items = load_items(rel, args.split)
                            n, i, o = judge_file(judge, variant, items, judge_dir(judge) / variant / rel)
                            print(f"[run] {judge:7} {variant:6} {rel:30} +{n:4} in={i:7} out={o:6}")

    if args.report:
        rep = report(args.split, args.variants, args.providers, args.judges)
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / f"judged_{args.split}.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n",
                                                          encoding="utf-8")
        print(f"{'task':10}{'variant':8}{'provider':9}{'judge':8}{'n':>6}{'acc':>7}{'chance':>8}"
              f"{'norm':>7}{'±sd':>6}{'retain':>8}{'tokW':>7}{'shared':>8}")
        for r in rep["rows"]:
            print(f"{r['task']:10}{r['variant']:8}{r['provider']:9}{r['judge']:8}{r['n']:6}{r['acc']:7.3f}"
                  f"{r['chance']:8.3f}{r['norm']:7.3f}{r['norm_sd']:6.3f}"
                  f"{r.get('retention', float('nan')):8.2f}{r.get('acc_token_weighted', float('nan')):7.3f}"
                  f"{r.get('acc_shared', float('nan')):8.3f}")
        if rep.get("judge_kappa"):
            print("judge agreement (Cohen's kappa):",
                  {k: round(v, 3) for k, v in rep["judge_kappa"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
