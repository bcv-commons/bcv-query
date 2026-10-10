// Interlinear for any Bible edition: the original-language scaffold from shoresh, joined in the browser to
//   - the edition's compact alignment (lexeme-aligner, Hugging Face, CC0), and
//   - the edition's chapter text (helloAO).
// shoresh only provides the scaffold; the alignment and the text never pass through it. No dependencies, no build: runs in a browser and in Node 18+.
//
//   const ch = await loadChapter({ iso: "fra", edition: "fra_lsg", book: "GEN", chapter: 1 });
//   ch.verses[0].source[1]   // { key, text, gloss, content, links: [{ i, text }], ... }  the Hebrew word and the French words aligned to it
//   ch.verses[0].target[2]   // { i, text, keys: ["010010010021"] }                       the French word and the source words behind it

import { tokenize, TOKENIZER_VERSION } from "./tokenize.js";

export const DEFAULTS = {
  shoresh: "https://shoresh.qombi.com",
  hf: "https://huggingface.co",
  helloao: "https://bible.helloao.org/api",
  dataset: "bcv-commons/compact-alignments",
};

const json = async (url) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
};

// The compact file is named <BOOK>_<hash>.json, and the hash is not known up front. One listing of the edition's folder gives it (cache the result).
// Files for the provenance and residual layers share the folder; they end in .meta.json / .extra.json and are not what we want here.
export async function findAlignmentFile({ iso, edition, book }, o = DEFAULTS) {
  const list = await json(`${o.hf}/api/datasets/${o.dataset}/tree/main/${iso[0]}/${iso}/${edition}`);
  const hit = list.find((f) => new RegExp(`/${book}_[0-9a-f]+\\.json$`).test(f.path));
  if (!hit) throw new Error(`no compact alignment for ${edition} ${book}`);
  return hit.path;
}

// The text of one verse as the aligner read it: a verse can arrive in several pieces (strings, or objects with `text`); notes and headings are not text.
export function verseText(item) {
  return item.content.map((c) => (typeof c === "string" ? c : c.text ?? "")).filter(Boolean).join(" ");
}

// "0:1 1:3,5 2:4-6" -> Map(srcOrd -> [target token positions]); an ordinal that is absent is unaligned.
export function decodeCompact(s) {
  const out = new Map();
  for (const part of s.split(" ").filter(Boolean)) {
    const [ord, span] = part.split(":");
    const idx = span.includes("-") ? (([a, b]) => Array.from({ length: b - a + 1 }, (_, k) => a + k))(span.split("-").map(Number)) : span.split(",").map(Number);
    out.set(Number(ord), { idx, scattered: span.includes(",") });
  }
  return out;
}

/**
 * @param {{iso:string, edition:string, textEdition?:string, book:string, chapter:number, glossLang?:string, verseMap?:(ref:string)=>string}} q
 *   edition is the folder name in the alignment dataset (eng_BSB); textEdition is the helloAO id when it differs (BSB). For most editions they are the same (fra_lsg).
 *   verseMap turns "BOOK C:V" in the edition's numbering into the aligner's (the original-language) numbering. Default: the same.
 *   Editions that number verses differently (see shoresh's /verse?edition= and the bibles versification maps) need it.
 */
export async function loadChapter(q, o = DEFAULTS) {
  const { iso, edition, book, chapter, glossLang } = q;
  const verseMap = q.verseMap ?? ((r) => r);
  const path = await findAlignmentFile({ iso, edition, book }, o);
  const raw = (p) => json(`${o.hf}/datasets/${o.dataset}/resolve/main/${p}`);
  const [scaffold, keys, compact, text, manifestHead] = await Promise.all([
    json(`${o.shoresh}/scaffold/${book}/${chapter}${glossLang ? `?gloss_lang=${encodeURIComponent(glossLang)}` : ""}`),
    raw(`_index/${book}_keys.json`),              // srcOrd -> MACULA token key, per verse; the same keys the scaffold uses
    raw(path),                                      // one compact string per verse, in the order of keys' own keys
    json(`${o.helloao}/${q.textEdition ?? edition}/${book}/${chapter}.json`),
    raw("manifest.json").then((m) => m.tokenizer_version),
  ]);
  if (manifestHead !== TOKENIZER_VERSION) throw new Error(`tokenizer version ${manifestHead} published, ${TOKENIZER_VERSION} implemented: refusing to decode`);

  const refs = Object.keys(keys);
  const alignment = new Map(refs.map((r, i) => [r, compact[i]]));
  const byKey = new Map(scaffold.tokens.map((t) => [t.key, t]));

  const verses = [];
  for (const item of text.chapter.content.filter((c) => c.type === "verse")) {
    const ref = `${book} ${chapter}:${item.number}`;
    const sref = verseMap(ref);
    const str = verseText(item);
    const target = tokenize(str).map((t, i) => ({ i, text: t, keys: [] }));
    const decoded = decodeCompact(alignment.get(sref) ?? "");
    // srcOrd counts content tokens only; keys[sref][ord] is that token's key (two keys joined by "+" when MACULA's node pair is one lexeme).
    const contentKeys = new Map((keys[sref] ?? []).map((k, ord) => [k, ord]));
    const links = new Map();                         // token key -> alignment
    for (const [k, ord] of contentKeys) {
      const a = decoded.get(ord);
      for (const part of k.split("+")) links.set(part, a ?? null);
      if (a) for (const i of a.idx) target[i]?.keys.push(...k.split("+"));
    }
    // The verse's source tokens in text order. The verse number is the scaffold's own (original numbering).
    const [sc, sv] = sref.split(" ")[1].split(":").map(Number);
    const source = scaffold.tokens.filter((t) => t.verse === sv && sc === chapter).map((t) => {
      const a = links.get(t.key);
      return { ...t, links: a ? a.idx.map((i) => target[i]).filter(Boolean) : [], scattered: !!a?.scattered, aligned: !!a };
    });
    verses.push({ ref, sourceRef: sref, text: str, target, source });
  }
  return { edition, book, chapter, alignmentFile: path, clauses: scaffold.clauses, phrases: scaffold.phrases, verses };
}
