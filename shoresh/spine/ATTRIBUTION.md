# Attribution & licensing — original-language spine

The spine is built from third-party data. Several sources are
**non-commercial (NC)**, which makes the spine — and any artifact derived
from it (e.g. the embedded `index.db`) — **non-commercial**. This project
operates under that constraint.

## Sources

| Source | Used for | License | Attribution |
|---|---|---|---|
| **unfoldingWord Hebrew Bible (UHB)** — `unfoldingWord/hbo_uhb` | OT spine (Strong's, lemma, morph per word) | CC BY-SA 4.0 | unfoldingWord® |
| **unfoldingWord Greek NT (UGNT)** — `unfoldingWord/el-x-koine_ugnt` | NT spine | CC BY-SA 4.0 | unfoldingWord® |
| **BHSA** — `ETCBC/bhsa` (via bcv-corpus) | syntactic roles (Layer 4) | CC BY-NC-SA 4.0 | ETCBC, VU Amsterdam |
| **OpenHebrewBible** — `eliranwong/OpenHebrewBible` | BHSA↔Strong's crosswalk (`002`), versification map (`019`) | **CC BY-NC 4.0** | Eliran Wong, *Open Hebrew Bible Project* |
| **STEPBible TBESH/TBESG** — `STEPBible/STEPBible-Data` | Strong's→gloss dictionary (Lexical line) | CC BY 4.0 | Tyndale House, *STEPBible.org* |

## What the NC clause means here

CC BY-NC (OpenHebrewBible) and CC BY-NC-SA (BHSA) require that the work
and its derivatives are **not used for commercial purposes**. Because the
spine prefix incorporates BHSA-derived syntax and crosswalk-derived
Strong's mappings, the resulting embeddings inherit NC. Keep the
deployment non-commercial, and carry attribution in any distributed
output.

Required attribution line (e.g. in the API/about page):

> Original-language data: unfoldingWord® UHB/UGNT (CC BY-SA 4.0); ETCBC
> BHSA (CC BY-NC-SA 4.0); Open Hebrew Bible Project by Eliran Wong
> (CC BY-NC 4.0).
