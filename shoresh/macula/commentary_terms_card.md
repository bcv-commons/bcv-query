---
license: cc-by-sa-4.0
language:
- hbo
pretty_name: Hebrew commentary terms
tags:
- bible
- hebrew
- tanakh
- rabbinic
- commentary
---

# hebrew-commentary-terms @TAG@

What the classical Hebrew commentators say about words and passages of the Tanakh, **in their own Hebrew terms**, as
statements on MACULA word keys. One row is one witness saying one thing about one stretch of text. Every statement here
comes from a fixed Hebrew formula in the commentary (rules); readings by a model are in the separate
[hebrew-commentary-terms-model](https://huggingface.co/datasets/bcv-commons/hebrew-commentary-terms-model).

A statement is a reading, not a fact of the text: each witness stands on its own, and witnesses may disagree.

## Tables

`data/statements.parquet` (@STATEMENTS@ rows):

| column | |
|---|---|
| `id` | statement id |
| `subject_first`, `subject_last` | MACULA word keys of the word or passage spoken about (a word: its parts; a psalm: the whole psalm) |
| `says` | `sense` (ענין X: the matter the word belongs to), `expression` (לשון X), `from_word` (מלשון X: the word it comes from), `gloss` (the comment opens with one Hebrew word that explains it), `kind` (what a psalm is: תפלה, שבח, הודאה …), `voice` (who says it: דוד, the exile …), `occasion` (the passage of the event it was said on), `cites` (the comment cites another verse: object = that verse; from v0.2) |
| `term` | the commentator's own Hebrew term, consonants as written (a leading ו dropped), or null for an occasion |
| `object_first`, `object_last` | for `occasion` and `cites`: MACULA keys of the verse the commentator cites |
| `witness`, `locus` | the work (`witnesses.tsv`) and the Sefaria reference of the comment |
| `formula` | the Hebrew formula the rule matched (ענין, לשון, מלשון; for psalms the opening words "המזמור הזה … אמרו"; for `cites` the lead words before the reference: שנאמר, זה שאמר הכתוב, כמו … or empty) |
| `register` | peshat, or derash where the sentence names a midrash or the sages |
| `anchor` | rule: the commentary's head word found in its verse by consonants, prefixes, lemma or full spelling |
| `citation` | the parenthesised verse reference as printed, for `occasion` and `cites` ("(שם …)" resolved to the citation before it) |
| `licence` | of the commentary text the row comes from |

`data/terms.parquet` (@TERMS@ terms): each term, how often each statement kind uses it, the biblical lemma it spells where that
is unambiguous (`lemma_strong`), and the sages' lists it is on.

`lists.tsv`: the sages' own lists of words, keyed by hand with their locus: ten words for joy (Avot de-Rabbi Natan 34), for
prayer (Sifrei Devarim 26), the ten kinds of praise in Psalms (Pesachim 117a), ten names for a prophet and for the holy
spirit (Avot de-Rabbi Natan 34).

`witnesses.tsv`: each work with its Hebrew title, author, century, the edition used and its licence.

## Counts

| witness | says | rows |
|---|---|---|
@BY_WITNESS@

Psalms with at least one opening statement by rule: @PSALMS@.

`cites` (from v0.2): the parenthesised verse references in the commentaries: the six on the Psalms (all verses), Midrash
Tehillim (which comments by psalm, not by verse: its subject is the whole psalm, register derash), and Metzudat Zion and Malbim
on the other books they cover. It maps which verses the commentators read together. A reference must name book, chapter and
verse; "(שם …)" (ibid) counts only in Midrash Tehillim and Radak, where it checks out (elsewhere it mostly gives a chapter); a
reference into its own subject is left out. Checked by machine: in about 94% the words printed just before or after the
reference are found in the cited verse (the rest is mostly a paraphrase or a printing slip).

## Sources and licence

Hebrew texts from Sefaria (https://www.sefaria.org), the open-licence version of each work: Metzudat Zion and Metzudat David
("On Your Way"), Radak on Psalms, Ibn Ezra on Psalms (Daat), Rashi (Sefaria Vocalized Edition, CC0, or On Your Way), Meiri on
Psalms (Jerusalem 1936), Malbim (On Your Way), Midrash Tehillim (On Your Way; from v0.2), Avot de-Rabbi Natan (Vilna 1883), Sifrei Devarim: Public Domain or CC0. The
Talmud list (Pesachim 117a) is from the Wikisource Talmud Bavli, CC BY-SA; for that row this dataset is CC BY-SA 4.0, and so
is the whole as published. Word keys: MACULA Hebrew (CC BY 4.0). The `licence` column gives each row's text licence.

## Provenance

Code @CODE@: `shoresh/macula/build_commentary_terms.py`, `hebrew_refs.py`, `release_commentary_terms.py`; Sefaria snapshot
2026-11-18 (`fetch_sefaria_psalms.py`; Metzudat Zion from the earlier cache of `build_metzudat_zion.py`).
