#!/usr/bin/env python3
"""Build per-language analyzer intent configs (fr/pt/ru/ar/hi).

NB: the committed configs are 3-letter ISO 639-3 (fra/por/…); this builder's keys
are 2-letter — a post-generation rename step (not in this script) produced the
final names. German (analyzer_lang/deu.json) was hand-authored to the same
capture-group contract below rather than regenerated here.

Replicates the es.json template (stopwords / topic_stopwords / relation_map /
patterns) for five more languages. Generated via Python so JSON/regex escaping
is handled by json.dump. See internal-docs/multilingual-unlock-plan.md (step 2)
and analyzer.py for the capture-group contract:
  entity[]            -> name in group(2)               (group1 = optional quote)
  genealogy           -> group(1)=relation, group(3)=name   ("relation of X")
  genealogy_possessive-> group(1)=name,     group(2)=relation ("X's relation")
  topic / xref        -> first non-empty (.+?) group

Name word-classes:
  Latin/Cyrillic (fr/pt/ru): [^\\W\\d_][\\w'’\\-]*  (combining marks rare/absent)
  Devanagari/Arabic (hi/ar): exclusion class — [^\\W\\d_] drops matras/harakat,
    so use a punctuation/space/digit-exclusion run (same idea as references._NAMEWORD).
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "resources" / "analyzer_lang"

# --- name capture fragments (group layout matters; see contract above) ---
# entity: (quote)(name)\1  -> name = group(2)
NM_LATIN = r"(['\"]?)([^\W\d_][\w'’\-]*)\1"
NM_EXCL  = r"(['\"]?)([^\s\d_.,:;!?()\[\]{}«»\"'“”’/\\।॥]+)\1"
# genealogy "relation <conn> name": rel=g1, quote=g2, name=g3
GNAME_LATIN = r"(['\"]?)([^\W\d_][\w'’\-]*)\2"
GNAME_EXCL  = r"(['\"]?)([^\s\d_.,:;!?()\[\]{}«»\"'“”’/\\।॥]+)\2"


CONFIGS = {
    # ------------------------------------------------------------------ FRENCH
    "fr": {
        "stopwords": ["le","la","les","l","un","une","des","de","du","d","à","au","aux",
            "et","ou","où","que","qui","quoi","quel","quelle","quels","quelles","dont",
            "ce","cet","cette","ces","mon","ma","mes","ton","ta","tes","son","sa","ses",
            "notre","nos","votre","vos","leur","leurs","je","tu","il","elle","on","nous",
            "vous","ils","elles","me","te","se","lui","y","en","ne","pas","plus","moins",
            "très","pour","par","avec","sans","sur","sous","dans","entre","vers","chez",
            "est","sont","était","étaient","sera","être","a","ont","avait","comme","si",
            "mais","donc","or","ni","car","ça","cela","celui","celle","ceux","quand",
            "comment","pourquoi","combien","aussi","tout","tous","toute","toutes"],
        "topic_stopwords": ["tout","tous","toute","toutes","quelque","chose","le","la",
            "les","un","une","ce","cela"],
        "relation_map": {"père":"father-of-rev","pere":"father-of-rev",
            "mère":"mother-of-rev","mere":"mother-of-rev","parents":"father-of-rev",
            "fils":"father-of","fille":"father-of","filles":"father-of","enfant":"father-of",
            "enfants":"father-of","frère":"sibling-of","frere":"sibling-of",
            "sœur":"sibling-of","soeur":"sibling-of","époux":"partner-of","epoux":"partner-of",
            "épouse":"partner-of","epouse":"partner-of","mari":"partner-of","femme":"partner-of",
            "conjoint":"partner-of"},
        "patterns": {
            "topic": r"(?:que|qu['’]?)\s*(?:dit|enseigne)\s+(?:la\s+)?bible\s+(?:sur|au\s+sujet\s+de|concernant|à\s+propos\s+de|de)\s+(.+?)(?:\?|$)|(?:versets?|passages?|écritures?|textes?)\s+(?:sur|au\s+sujet\s+de|concernant|à\s+propos\s+de)\s+(.+?)(?:\?|$)",
            "entity": [
                r"^\s*qui\s+(?:est|était|sont|étaient|fut|furent)\s+(?:le\s+|la\s+|les\s+)?" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*(?:qu['’]est[- ]ce\s+que?|quel(?:le)?\s+est)\s+(?:le\s+|la\s+|un\s+|une\s+|l['’])?" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*que\s+(?:signifie|veut\s+dire)\s+(?:le\s+terme\s+|le\s+mot\s+|le\s+|la\s+|l['’])?" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*(?:parle|parlez)[- ]?moi\s+(?:de|du|des|de\s+la|de\s+l['’])\s*" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*défini(?:s|ssez|r)\s+" + NM_LATIN + r"\s*\??\s*$",
            ],
            "xref": r"références?\s+crois[ée]es?\s+(?:pour|de|à)\s+(.+?)(?:\?|$)|passages?\s+parallèles?\s+(?:à|de|pour)\s+(.+?)(?:\?|$)|(?:versets?|passages?)\s+(?:liés?|relatifs?)\s+(?:à|aux?|avec)\s+(.+?)(?:\?|$)",
            "genealogy": r"\b(père|pere|mère|mere|parents|fils|fille|filles|enfant|enfants|frère|frere|sœur|soeur|époux|epoux|épouse|epouse|mari|femme|conjoint)\s+(?:de\s+la|du|des|de|d['’])\s*" + GNAME_LATIN,
        },
    },
    # -------------------------------------------------------------- PORTUGUESE
    "pt": {
        "stopwords": ["o","a","os","as","um","uma","uns","umas","de","do","da","dos","das",
            "em","no","na","nos","nas","ao","à","aos","às","e","ou","que","quem","qual",
            "quais","quando","como","onde","por","para","com","sem","sobre","entre","é",
            "são","era","eram","foi","foram","ser","tem","têm","há","este","esta","isto",
            "esse","essa","isso","aquele","aquela","aquilo","meu","minha","seu","sua","nós",
            "eu","ele","ela","eles","elas","se","lhe","lhes","não","mais","muito","também",
            "já","porque","mas","do","seus","suas","te","me","ainda","cada","todo","todos",
            "toda","todas"],
        "topic_stopwords": ["todo","todos","toda","todas","algo","alguma","algum","isto",
            "isso","o","a","os","as","um","uma"],
        "relation_map": {"pai":"father-of-rev","mãe":"mother-of-rev","mae":"mother-of-rev",
            "pais":"father-of-rev","filho":"father-of","filha":"father-of","filhos":"father-of",
            "filhas":"father-of","irmão":"sibling-of","irmao":"sibling-of","irmã":"sibling-of",
            "irma":"sibling-of","irmãos":"sibling-of","esposo":"partner-of","esposa":"partner-of",
            "marido":"partner-of","mulher":"partner-of","cônjuge":"partner-of","conjuge":"partner-of"},
        "patterns": {
            "topic": r"(?:o\s+que|que)\s+(?:a\s+)?b[íi]blia\s+(?:diz|ensina|fala)\s+(?:sobre|acerca\s+de|a\s+respeito\s+de|de)\s+(.+?)(?:\?|$)|(?:vers[íi]culos?|passagens?|escrituras?|textos?)\s+(?:sobre|acerca\s+de|a\s+respeito\s+de)\s+(.+?)(?:\?|$)",
            "entity": [
                r"^\s*quem\s+(?:é|era|foi|são|eram|foram)\s+(?:o\s+|a\s+|os\s+|as\s+)?" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*o\s+que\s+(?:é|era|foi|são)\s+(?:o\s+|a\s+|um\s+|uma\s+)?" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*o\s+que\s+significa\s+(?:o\s+termo\s+|a\s+palavra\s+|o\s+|a\s+)?" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*(?:fale|conte)[- ]?(?:me)?\s+(?:sobre|acerca\s+de|de)\s+(?:o\s+|a\s+)?" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*defin[ae](?:r|\s)?\s*" + NM_LATIN + r"\s*\??\s*$",
            ],
            "xref": r"refer[êe]ncias?\s+cruzadas?\s+(?:para|de|a)\s+(.+?)(?:\?|$)|passagens?\s+paralelas?\s+(?:a|de|para)\s+(.+?)(?:\?|$)|(?:vers[íi]culos?|passagens?)\s+relacionad[oa]s?\s+(?:a|com)\s+(.+?)(?:\?|$)",
            "genealogy": r"\b(pai|mãe|mae|pais|filho|filha|filhos|filhas|irmão|irmao|irmã|irma|irmãos|esposo|esposa|marido|mulher|cônjuge|conjuge)\s+(?:de\s+a|do|da|dos|das|de)\s*" + GNAME_LATIN,
        },
    },
    # ------------------------------------------------------------------ RUSSIAN
    "ru": {
        "stopwords": ["и","в","во","не","что","он","на","я","с","со","как","а","то","все",
            "она","так","его","но","да","ты","к","у","же","вы","за","бы","по","ее","мне",
            "было","вот","от","меня","еще","нет","о","из","ему","когда","даже","ну","ли",
            "если","или","ни","быть","был","была","были","кто","это","этот","эта","эти",
            "где","чем","для","чтобы","при","про","без","над","под","между","я","мы","они",
            "она","оно","там","тут","этого","той","том","тем","который","которая"],
        "topic_stopwords": ["все","всё","что-то","нечто","это","то","этот","эта","тот"],
        "relation_map": {"отец":"father-of-rev","мать":"mother-of-rev","родители":"father-of-rev",
            "сын":"father-of","дочь":"father-of","дети":"father-of","брат":"sibling-of",
            "сестра":"sibling-of","муж":"partner-of","жена":"partner-of","супруг":"partner-of",
            "супруга":"partner-of"},
        "patterns": {
            "topic": r"что\s+(?:говорит|сказано\s+в)\s+библи[яи]\s+о(?:б)?\s+(.+?)(?:\?|$)|(?:стих[иа]?|отрывк[иа]?|места?)\s+о(?:б)?\s+(.+?)(?:\?|$)",
            "entity": [
                r"^\s*кто\s+так(?:ой|ая|ие|ое)\s+" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*кто\s+(?:есть|был|была|были)\s+" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*что\s+так(?:ое|ой)\s+" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*что\s+(?:означает|значит)\s+(?:слово\s+|термин\s+)?" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*(?:расскажи|дай\s+определение)\s+(?:о(?:б)?\s+)?" + NM_LATIN + r"\s*\??\s*$",
            ],
            "xref": r"перекр[ёе]стны[ехй]+\s+ссылк[иа]?\s+(?:для|к|на)\s+(.+?)(?:\?|$)|параллельны[ехй]+\s+места?\s+(?:к|для)\s+(.+?)(?:\?|$)|(?:стих[иа]?|отрывк[иа]?)\s+связанны[ехй]+\s+с\s+(.+?)(?:\?|$)",
            # Russian genitive, no connector: "отец Давида"
            "genealogy": r"\b(отец|мать|родители|сын|дочь|дети|брат|сестра|муж|жена|супруг|супруга)\s+" + GNAME_LATIN,
        },
    },
    # ------------------------------------------------------------------- ARABIC
    "ar": {
        "stopwords": ["في","من","إلى","على","عن","مع","هذا","هذه","ذلك","تلك","التي","الذي",
            "ما","ماذا","هل","و","أو","ثم","لا","لم","لن","إن","أن","كان","كانت","يكون","هو",
            "هي","هم","أنا","أنت","نحن","قد","كل","بعض","عند","له","لها","هناك","أي","الى",
            "او","انا","انت","هذة","الذين","كما","بين","حول","عند"],
        "topic_stopwords": ["كل","بعض","شيء","هذا","هذه","ذلك","ال"],
        "relation_map": {"أب":"father-of-rev","اب":"father-of-rev","والد":"father-of-rev",
            "أم":"mother-of-rev","ام":"mother-of-rev","والدة":"mother-of-rev",
            "ابن":"father-of","إبن":"father-of","ابنة":"father-of","بنت":"father-of",
            "أخ":"sibling-of","اخ":"sibling-of","أخت":"sibling-of","اخت":"sibling-of",
            "زوج":"partner-of","زوجة":"partner-of"},
        "patterns": {
            "topic": r"ماذا\s+يقول\s+الكتاب\s+المقدس\s+عن\s+(.+?)(?:\?|؟|$)|(?:آيات|نصوص|مقاطع|شواهد)\s+(?:عن|حول|بخصوص)\s+(.+?)(?:\?|؟|$)",
            "entity": [
                r"^\s*من\s+(?:هو|هي|هم)\s+" + NM_EXCL + r"\s*(?:\?|؟)?\s*$",
                r"^\s*ما\s+(?:هو|هي)\s+" + NM_EXCL + r"\s*(?:\?|؟)?\s*$",
                r"^\s*(?:ماذا\s+يعني|ما\s+معنى|ما\s+هو\s+معنى)\s+(?:كلمة\s+|مصطلح\s+)?" + NM_EXCL + r"\s*(?:\?|؟)?\s*$",
                r"^\s*(?:أخبرني|حدثني)\s+عن\s+" + NM_EXCL + r"\s*(?:\?|؟)?\s*$",
                r"^\s*عرّ?ف\s+" + NM_EXCL + r"\s*(?:\?|؟)?\s*$",
            ],
            "xref": r"(?:المراجع|الإحالات)\s+المتقاطعة\s+ل(?:ـ)?\s*(.+?)(?:\?|؟|$)|(?:المقاطع|الآيات)\s+المواز(?:ية|ي)\s+ل(?:ـ)?\s*(.+?)(?:\?|؟|$)|آيات\s+(?:متعلقة|مرتبطة)\s+ب(?:ـ)?\s*(.+?)(?:\?|؟|$)",
            # Arabic construct state, no connector: "والد داود"
            "genealogy": r"(?<!\S)(أب|اب|أبو|والد|أم|ام|والدة|ابن|إبن|ابنة|بنت|أخ|اخ|أخت|اخت|زوج|زوجة)\s+" + GNAME_EXCL,
        },
    },
    # -------------------------------------------------------------------- HINDI
    "hi": {
        "stopwords": ["का","के","की","में","से","को","पर","और","या","है","हैं","था","थे","थी",
            "क्या","कौन","कब","कहाँ","कैसे","क्यों","यह","वह","ये","वे","जो","जब","तक","एक",
            "इस","उस","ने","भी","नहीं","हाँ","बहुत","अधिक","लिए","साथ","बिना","ऊपर","नीचे",
            "बीच","मैं","तुम","आप","हम","कि","तो","ही","अपने","अपना","उन","इन","कोई","कुछ"],
        "topic_stopwords": ["सब","सभी","कुछ","कोई","यह","वह","एक","इस","उस"],
        "relation_map": {"पिता":"father-of-rev","माता":"mother-of-rev","माँ":"mother-of-rev",
            "माता-पिता":"father-of-rev","पुत्र":"father-of","बेटा":"father-of","पुत्री":"father-of",
            "बेटी":"father-of","भाई":"sibling-of","बहन":"sibling-of","पति":"partner-of",
            "पत्नी":"partner-of"},
        "patterns": {
            # Hindi: topic word precedes "के बारे में"
            "topic": r"बाइबल\s+(.+?)\s+(?:के\s+बारे\s+में|के\s+विषय\s+में)\s+क्या\s+(?:कहती|बताती)\s+है|(.+?)\s+(?:के\s+बारे\s+में|के\s+विषय\s+में)\s+(?:आयतें|वचन|पद|शास्त्र)",
            "entity": [
                r"^\s*" + NM_EXCL + r"\s+कौन\s+(?:है|था|थी|हैं|थे)\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+क्या\s+(?:है|था|थी|हैं)\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+(?:का|के)\s+(?:अर्थ|मतलब)\s+क्या\s+है\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+के\s+बारे\s+में\s+(?:बताओ|बताइए|बताएं)\s*\??\s*$",
            ],
            "xref": r"(.+?)\s+के\s+लिए\s+(?:क्रॉस[- ]?रेफरेंस|पारस्परिक\s+संदर्भ)|(.+?)\s+(?:से\s+संबंधित|के\s+समानांतर)\s+(?:आयतें|वचन|अंश|पद)",
            # Hindi reversed "X का पिता" -> possessive slot (g1=name, g2=relation)
            "genealogy_possessive": r"([^\s\d_.,:;!?()\[\]{}«»\"'“”’/\\।॥]+)\s+(?:का|के|की)\s+(माता-पिता|पिता|माता|माँ|पुत्र|बेटा|पुत्री|बेटी|भाई|बहन|पति|पत्नी)",
        },
    },
    # ------------------------------------------------------------------ BENGALI
    # Indic (combining-mark-safe name class) + reversed "X এর পিতা" possessive.
    # Machine-authored — trigger phrasing warrants native review.
    "bn": {
        "stopwords": ["এর","র","এ","তে","কে","এবং","ও","বা","হয়","হল","ছিল","কি","কী",
            "কখন","কোথায়","কীভাবে","কেন","এই","সেই","যে","যখন","একটি","একজন","না","নেই",
            "আছে","জন্য","সাথে","সঙ্গে","উপর","মধ্যে","থেকে","দিয়ে","আমি","তুমি","আপনি",
            "আমরা","সে","তারা","তিনি","এটা","ওটা","সব","কিছু","করে","হবে","ছিলেন","কিন্তু"],
        "topic_stopwords": ["সব","সকল","কিছু","কোনো","এই","সেই","একটি","একজন","এটা"],
        "relation_map": {"পিতা":"father-of-rev","বাবা":"father-of-rev","মাতা":"mother-of-rev",
            "মা":"mother-of-rev","পুত্র":"father-of","ছেলে":"father-of","কন্যা":"father-of",
            "মেয়ে":"father-of","ভাই":"sibling-of","বোন":"sibling-of","স্বামী":"partner-of",
            "স্ত্রী":"partner-of"},
        "patterns": {
            "topic": r"বাইবেল\s+(.+?)\s+(?:সম্পর্কে|বিষয়ে)\s+কী\s+বলে|(.+?)\s+(?:সম্পর্কে|বিষয়ে)\s+(?:আয়াত|পদ|বচন|শাস্ত্র)",
            "entity": [
                r"^\s*" + NM_EXCL + r"\s+কে\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+(?:কী|কি)\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+এর\s+(?:অর্থ|মানে)\s+(?:কী|কি)\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+(?:সম্পর্কে|বিষয়ে)\s+বল(?:ুন|ো)\s*\??\s*$",
            ],
            "xref": r"(.+?)\s+এর\s+(?:সাথে|সঙ্গে)\s+সম্পর্কিত\s+(?:আয়াত|পদ)|(.+?)\s+এর\s+সমান্তরাল\s+(?:অংশ|পদ)",
            # reversed possessive: name (with genitive ের/এর) + relation
            "genealogy_possessive": r"([^\s\d_.,:;!?()\[\]{}«»\"'“”’/\\।॥]+(?:ের|এর))\s+(পিতা|বাবা|মাতা|মা|পুত্র|ছেলে|কন্যা|মেয়ে|ভাই|বোন|স্বামী|স্ত্রী)",
        },
    },
    # ----------------------------------------------------------------- ASSAMESE
    # Assamese script (≈ Bengali) + reversed possessive (genitive ৰ). Machine-
    # authored — native review advised (esp. colloquial kinship terms).
    "as": {
        "stopwords": ["ৰ","অৰ","ত","ক","আৰু","ও","বা","হয়","আছিল","কি","কোন","কেতিয়া",
            "ক'ত","কেনেকৈ","কিয়","এই","সেই","যে","যেতিয়া","এটা","এজন","নহয়","নাই","আছে",
            "বাবে","লগত","সৈতে","ওপৰত","মাজত","পৰা","মই","তুমি","আপুনি","আমি","সি","তেওঁ",
            "সিহঁত","এইটো","সকলো","কিছু","কৰি","হ'ব","কিন্তু"],
        "topic_stopwords": ["সকলো","কিছু","কোনো","এই","সেই","এটা","এজন"],
        "relation_map": {"পিতৃ":"father-of-rev","দেউতা":"father-of-rev","বাপেক":"father-of-rev",
            "মাতৃ":"mother-of-rev","মা":"mother-of-rev","আই":"mother-of-rev","পুত্ৰ":"father-of",
            "ল'ৰা":"father-of","কন্যা":"father-of","ছোৱালী":"father-of","ভাই":"sibling-of",
            "ককাই":"sibling-of","ভনী":"sibling-of","স্বামী":"partner-of","পত্নী":"partner-of",
            "তিৰোতা":"partner-of"},
        "patterns": {
            "topic": r"বাইবেলে?\s+(.+?)\s+(?:সম্পৰ্কে|বিষয়ে)\s+কি\s+কয়|(.+?)\s+(?:সম্পৰ্কে|বিষয়ে)\s+(?:আয়াত|পদ|বচন|শাস্ত্ৰ)",
            "entity": [
                r"^\s*" + NM_EXCL + r"\s+কোন\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+কি\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+ৰ\s+(?:অৰ্থ|মানে)\s+কি\s*\??\s*$",
                r"^\s*" + NM_EXCL + r"\s+(?:সম্পৰ্কে|বিষয়ে)\s+কোৱা\s*\??\s*$",
            ],
            "xref": r"(.+?)\s+ৰ\s+সৈতে\s+সম্পৰ্কিত\s+(?:আয়াত|পদ)|(.+?)\s+ৰ\s+সমান্তৰাল\s+(?:অংশ|পদ)",
            "genealogy_possessive": r"([^\s\d_.,:;!?()\[\]{}«»\"'“”’/\\।॥]+ৰ)\s+(পিতৃ|দেউতা|বাপেক|মাতৃ|মা|আই|পুত্ৰ|ল'ৰা|কন্যা|ছোৱালী|ভাই|ককাই|ভনী|স্বামী|পত্নী|তিৰোতা)",
        },
    },
    # -------------------------------------------------------------------- HAUSA
    # Latin script (incl. hooked ɓ ɗ ƙ — Unicode letters, matched by \w). NT-only.
    # Construct-state genealogy "uban Dauda". Machine-authored — native review advised.
    "ha": {
        "stopwords": ["na","ta","da","a","ya","su","ba","ne","ce","ko","kuma","amma","don",
            "saboda","wannan","waɗannan","cikin","kan","ga","zuwa","wa","me","yaya","ina",
            "wane","wace","shi","ita","ni","kai","ke","mu","ku","sai","fa","suka","za","zai",
            "ana","akwai","wani","wata","wasu","duk","ma","yake","take"],
        "topic_stopwords": ["duk","dukan","wasu","wannan","waɗannan","wani","wata"],
        "relation_map": {"uba":"father-of-rev","mahaifi":"father-of-rev","uwa":"mother-of-rev",
            "mahaifiya":"mother-of-rev","ɗa":"father-of","ɗiya":"father-of","miji":"partner-of",
            "mata":"partner-of","ɗan'uwa":"sibling-of","'yar'uwa":"sibling-of"},
        "patterns": {
            "topic": r"menene\s+littafi\s+mai\s+tsarki\s+(?:ya\s+ce|yake\s+ce(?:wa)?)\s+(?:game\s+da|akan)\s+(.+?)(?:\?|$)|ayoyi\s+(?:game\s+da|akan)\s+(.+?)(?:\?|$)",
            "entity": [
                r"^\s*wane\s+ne\s+" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*wace\s+ce\s+" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*menene\s+" + NM_LATIN + r"\s*\??\s*$",
                r"^\s*me\s+(?:ake\s+nufi\s+da|ne)\s+" + NM_LATIN + r"\s*\??\s*$",
            ],
            "xref": r"ayoyi\s+masu\s+ala[ƙk]a\s+da\s+(.+?)(?:\?|$)|ayoyi\s+(?:da\s+suka\s+yi\s+kama\s+da|kamar)\s+(.+?)(?:\?|$)",
            # construct state: relation + (optional -n linker) + name
            "genealogy": r"(?<!\S)(uba|mahaifi|uwa|mahaifiya|ɗa|ɗiya|miji|mata)n?\s+" + GNAME_LATIN,
        },
    },
}

HDR = ("{lang} intent config for the analyzer. patterns override the English "
       "trigger regexes (analyzer.py); absent keys fall back to English. "
       "Built by scripts/build_analyzer_lang.py. See internal-docs/multilingual-unlock-plan.md.")
NAMES = {"fr":"French","pt":"Portuguese","ru":"Russian","ar":"Arabic","hi":"Hindi",
         "bn":"Bengali","as":"Assamese","ha":"Hausa"}

for lang, cfg in CONFIGS.items():
    out = {"_comment": HDR.format(lang=NAMES[lang])}
    out.update(cfg)
    path = OUT / f"{lang}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}  ({len(cfg['stopwords'])} stopwords, "
          f"{len(cfg['relation_map'])} relations, "
          f"{len(cfg['patterns'])} pattern groups)")
