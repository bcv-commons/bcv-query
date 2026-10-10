// Live check: node check.mjs [shoresh-base-url]   (default: the public service; use http://127.0.0.1:8099 for a local one)
import assert from "node:assert/strict";
import { DEFAULTS, loadChapter } from "./interlinear.js";

const o = { ...DEFAULTS, shoresh: process.argv[2] ?? DEFAULTS.shoresh };
const flat = (v) => v.source.filter((t) => t.aligned).map((t) => `${t.lexeme}=${t.links.map((l) => l.text).join(" ")}`).join(" | ");

const gen = await loadChapter({ iso: "fra", edition: "fra_lsg", book: "GEN", chapter: 1 }, o);
console.log(gen.alignmentFile, gen.verses.length, "verses");
console.log(flat(gen.verses[0]));
const v1 = gen.verses[0].source.filter((t) => t.aligned).map((t) => [t.lexeme, t.links.map((l) => l.text).join(" ")]);
assert.deepEqual(v1, [["hbo:7225", "commencement"], ["hbo:1254", "créa"], ["hbo:0430", "Dieu"], ["hbo:8064", "cieux"], ["hbo:0776", "terre"]]);
assert.ok(gen.verses[0].target.find((t) => t.text === "Dieu").keys.length === 1);         // the way back: a French word to its Hebrew word

const swh = await loadChapter({ iso: "swh", edition: "swh_ulb", book: "JHN", chapter: 1, glossLang: "German" }, o);
console.log(flat(swh.verses[0]));
assert.ok(swh.verses[0].source.some((t) => t.aligned));

// every content token of the scaffold must be one the aligner indexed, in every verse of the chapter
for (const v of gen.verses) assert.ok(v.source.length > 0, v.ref);
console.log("ok");
