"""Source readers for the source-examples builders (SPEC 1.0, section 5).

Reads MACULA lowfat files (Hebrew/Aramaic WLC, Greek Nestle 1904) and the Hebrew node files. Uses only
xml.etree.ElementTree, which executes nothing. Results are plain tuples and dicts; a parse is cached as a pickle
under /tmp/claude-1000/source-examples/cache/, keyed by the sha256 of every file read, so a changed source is
re-read. Delete nothing: a stale cache simply has another key.
"""
import glob
import hashlib
import multiprocessing as mp
import os
import pickle
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
HEB_LOWFAT = os.path.join(HERE, ".lowfat-src/WLC/lowfat")
GRC_LOWFAT = os.path.join(HERE, ".lowfat-src-grc")
HEB_NODES = os.path.join(HERE, "data/macula-nodes/hebrew/WLC/nodes")
GRC_NODES = os.path.join(HERE, "data/macula-nodes/greek/Nestle1904/nodes")
CACHE = "/tmp/claude-1000/source-examples/cache"
XID = "{http://www.w3.org/XML/1998/namespace}id"
PROCS = 7

HEB_ATTRS = ("ref", "class", "pos", "lemma", "strongnumberx", "lang", "after",
             "type", "stem", "person", "gender", "number", "state",
             "subjref", "participantref", "frame")
GRC_ATTRS = ("ref", "class", "lemma", "strong", "normalized", "after",
             "type", "tense", "voice", "mood", "person", "case", "gender", "number", "degree",
             "subjref", "referent")


def heb_lowfat_files():
    return sorted(glob.glob(os.path.join(HEB_LOWFAT, "*-lowfat.xml")))


def grc_lowfat_files():
    return sorted(glob.glob(os.path.join(GRC_LOWFAT, "*.xml")))


def heb_node_files():
    return sorted(glob.glob(os.path.join(HEB_NODES, "*.xml")))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _files_key(files):
    h = hashlib.sha256()
    for f in files:
        h.update(os.path.basename(f).encode())
        h.update(sha256(f).encode())
    return h.hexdigest()[:16]


def _cached(name, files, worker):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{name}-{_files_key(files)}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return pickle.load(fh)
    with mp.get_context("fork").Pool(PROCS) as pool:
        res = pool.map(worker, files, chunksize=4)
    tmp = path + f".tmp{os.getpid()}"
    with open(tmp, "wb") as fh:
        pickle.dump(res, fh, protocol=5)
    os.replace(tmp, path)
    return res


# ---- lowfat ---------------------------------------------------------------------------------------------------

def _parse_lowfat(path, attrs):
    """One file -> (basename, milestones, sentences). A sentence is (pieces, compound_ids); a piece is a dict of
    the attributes in `attrs` that are present, plus `id`, `text` and `doc` (document order in the sentence)."""
    root = ET.parse(path).getroot()
    milestones = [m.get("id") for m in root.iter("milestone") if m.get("unit") == "verse"]
    sents = []
    for s in root.iter("sentence"):
        pieces = []
        for i, w in enumerate(s.iter("w")):
            d = {k: w.get(k) for k in attrs if w.get(k) is not None}
            d["id"] = w.get(XID)
            d["text"] = w.text or ""
            d["doc"] = i
            pieces.append(d)
        compound = []
        for c in s.iter("c"):
            compound.append(tuple(w.get(XID) for w in c if w.tag == "w"))
        sents.append((pieces, compound))
    return os.path.basename(path), milestones, sents


def _heb_lowfat(path):
    return _parse_lowfat(path, HEB_ATTRS)


def _grc_lowfat(path):
    return _parse_lowfat(path, GRC_ATTRS)


def heb_lowfat():
    return _cached("heb-lowfat", heb_lowfat_files(), _heb_lowfat)


def grc_lowfat():
    return _cached("grc-lowfat", grc_lowfat_files(), _grc_lowfat)


# ---- Hebrew node files: morphId of every piece, StrongNumberX of compounds -------------------------------------

def _heb_nodes(path):
    """One node file -> list of (pid, morphId, word ref, compound strong or None, compound rank or 0, m text)."""
    root = ET.parse(path).getroot()
    out = []
    for node in root.iter("Node"):
        c = node.find("c")
        if c is not None:
            for r, m in enumerate(c.findall("m"), 1):
                out.append((m.get(XID), node.get("morphId"), m.get("word"), node.get("StrongNumberX"), r,
                            m.text or ""))
            continue
        if node.find("Node") is not None:
            continue
        m = node.find("m")
        if m is None:
            continue
        out.append((m.get(XID), node.get("morphId"), m.get("word"), None, 0, m.text or ""))
    return os.path.basename(path), out


def heb_nodes():
    return _cached("heb-nodes", heb_node_files(), _heb_nodes)


# ---- node trees (stage 03): every node with Cat, Rule, Head; leaves as piece ids --------------------------------

def _walk_nodes(el, nodes, leafcat, greek):
    """Append the node `el` (and its subtree) to `nodes`; return its index. A node is
    [cat, rule, head, kids, kind]: kind 'n' (a node with Node children), 'c' (a compound: kids are the pids of its
    `m`), 'w' (a leaf: kids is [pid]). Head is the source's string or None."""
    i = len(nodes)
    c = el.find("c")
    if c is not None:
        pids = [m.get(XID) for m in c.findall("m")]
        for p in pids:
            leafcat[p] = el.get("Cat")
        nodes.append([el.get("Cat"), el.get("Rule"), el.get("Head"), pids, "c"])
        return i
    kids_el = [k for k in el if k.tag == "Node"]
    if not kids_el:
        if greek:
            pid = el.get(XID)
        else:
            m = el.find("m")
            pid = m.get(XID) if m is not None else None
        if pid is None:
            raise ValueError(f"leaf node without a piece id: {el.attrib}")
        leafcat[pid] = el.get("Cat")
        nodes.append([el.get("Cat"), el.get("Rule"), el.get("Head"), [pid], "w"])
        return i
    nodes.append([el.get("Cat"), el.get("Rule"), el.get("Head"), None, "n"])
    nodes[i][3] = [_walk_nodes(k, nodes, leafcat, greek) for k in kids_el]
    return i


def _trees(path, greek):
    """One node file -> (basename, sentences); a sentence is (ref, top node indices, nodes, leafcat)."""
    import sys
    sys.setrecursionlimit(20000)
    root = ET.parse(path).getroot()
    out = []
    for s in root.iter("Sentence"):
        nodes, leafcat, tops = [], {}, []
        for tree in s.findall("./Trees/Tree"):
            for k in tree:
                if k.tag == "Node":
                    tops.append(_walk_nodes(k, nodes, leafcat, greek))
        out.append((s.get("verse") or s.get("ref"), tops, nodes, leafcat))
    return os.path.basename(path), out


def _heb_trees(path):
    return _trees(path, False)


def _grc_trees(path):
    return _trees(path, True)


def grc_node_files():
    return sorted(glob.glob(os.path.join(GRC_NODES, "*.xml")))


def heb_trees():
    return _cached("heb-trees", heb_node_files(), _heb_trees)


def grc_trees():
    return _cached("grc-trees", grc_node_files(), _grc_trees)


# ---- lowfat elements (stage 03): every element that holds pieces, with its pieces -----------------------------

def _lowfat_elements(path):
    """One lowfat file -> (basename, sentences); a sentence is a list of elements in document order (preorder,
    so an element comes before the elements inside it): (tag, role, class, rule, head, type, pids, parent index or
    -1). Tags: wg, w, c."""
    root = ET.parse(path).getroot()
    out = []
    for s in root.iter("sentence"):
        els = []

        def walk(el, parent):
            if el.tag not in ("wg", "w", "c"):
                for k in el:
                    walk(k, parent)
                return []
            i = len(els)
            els.append(None)
            if el.tag == "w":
                pids = [el.get(XID)]
            else:
                pids = []
                for k in el:
                    pids.extend(walk(k, i))
            els[i] = (el.tag, el.get("role"), el.get("class"), el.get("rule"), el.get("head"), el.get("type"),
                      tuple(pids), parent)
            return pids

        for k in s:
            walk(k, -1)
        out.append(els)
    return os.path.basename(path), out


def heb_lowfat_elements():
    return _cached("heb-lowfat-els", heb_lowfat_files(), _lowfat_elements)


def grc_lowfat_elements():
    return _cached("grc-lowfat-els", grc_lowfat_files(), _lowfat_elements)
