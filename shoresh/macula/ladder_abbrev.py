"""The abbreviation table of the Hebrew ladder (SPEC-ladder 4.4, rule AB). Fixed, part of the builder, the same in every build.

Rows are (abbrev, written, kind). `abbrev` is written as Metzudat David writes it (gershayim U+05F4, geresh U+05F3; two
rows keep the ASCII quote the source also uses). Kinds: `word` (written out in tokens), `divine_name` (written out as the
Bible's form, also used by rule MA), `number` (a numeral, kept as written), `match` (rule MA only; none so far).

HEAD = the rows SPEC-ladder 4.4 fixes. ADDED = the rows stage 58 added from the counts (listed in its report).
NUMBERS = the numerals, generated: the 22 single letters with geresh, and the two-letter numerals tens + units
(with ט״ו and ט״ז for 15 and 16); כ״א is a `word` row (SPEC-ladder 4.4, L-5) and so is left out here.
"""

HEAD = [
    ("ר״ל", "רצה לומר", "word"),
    ("ה׳", "יהוה", "divine_name"),
    ("וכו׳", "וכולי", "word"),
    ("וגו׳", "וגומר", "word"),
    ("במ״ש", "במה שאמר", "word"),
    ("כמ״ש", "כמו שאמר", "word"),
    ("כ״א", "כל אחד", "word"),
    ("א״כ", "אם כן", "word"),
    ("עכו״ם", "עובדי כוכבים ומזלות", "word"),
    ("ע״י", "על ידי", "word"),
    ("עכ״ז", "עם כל זה", "word"),
    ("נ״נ", "נבוכדנאצר", "word"),
    ("מ״מ", "מכל מקום", "word"),
    ("ז״ל", "זכרונו לברכה", "word"),
    ("א״י", "ארץ ישראל", "word"),
    ("כ״כ", "כל כך", "word"),
    ("ע״ש", "על שם", "word"),
    ("ארז״ל", "אמרו רבותינו זכרונם לברכה", "word"),
    ("ע״פ", "על פי", "word"),
    ("ב״ה", "בית המקדש", "word"),
    ("אח״ז", "אחר זה", "word"),
    ("קה״ק", "קודש הקדשים", "word"),
    ("רז״ל", "רבותינו זכרונם לברכה", "word"),
    ("במ״ב", "במה שאמר בו", "word"),
    ("בה״מ", "בית המקדש", "word"),
    ("כ״ש", "כל שכן", "word"),
    ("א״א", "אי אפשר", "word"),
    ("עי״ז", "על ידי זה", "word"),
    ("בל׳", "בלשון", "word"),
    ("במ״א", "במקום אחר", "word"),
    ("אד׳", "אדני", "divine_name"),
    ("אלקים", "אלהים", "divine_name"),
    ("אלקי", "אלהי", "divine_name"),
    ("אלקיך", "אלהיך", "divine_name"),
    ("אלקינו", "אלהינו", "divine_name"),
    ("אלקיו", "אלהיו", "divine_name"),
    ("אלקיהם", "אלהיהם", "divine_name"),
    ("אלקיכם", "אלהיכם", "divine_name"),
]

ADDED = [
    # the same abbreviations written with the ASCII quote, as the source also writes them
    ('ר"ל', "רצה לומר", "word"),
    ("ה'", "יהוה", "divine_name"),
    # from the counts of the cleaned body tokens (stage 58), commonest first
    ("מ״ש", "מה שאמר", "word"),
    ("ה״א", "הא", "word"),            # the letter's name (בה״א השאלה)
    ("בד״ה", "בדברי הימים", "word"),
    ("ש״א", "שמואל א", "word"),
    ("ש״ב", "שמואל ב", "word"),
    ("ת״י", "תרגום יונתן", "word"),
    ("ה״ה", "הוא הדין", "word"),
    ("ס״ע", "סדר עולם", "word"),
    ("ע״נ", "עזרת נשים", "word"),
    ("ע״ג", "על גבי", "word"),
    ("ר״ה", "ראש השנה", "word"),
    ("הקב״ה", "הקדוש ברוך הוא", "word"),
    ("עוה״ב", "עולם הבא", "word"),
    ("עוה״ז", "עולם הזה", "word"),
    ("ז״ש", "זהו שאמר", "word"),
    ("ג״כ", "גם כן", "word"),
    ("משא״כ", "מה שאין כן", "word"),
    ("מכ״ש", "מכל שכן", "word"),
    ("אפי׳", "אפילו", "word"),
    ("יצה״ר", "יצר הרע", "word"),
    ("לה״ר", "לשון הרע", "word"),
    ("רה״ק", "רוח הקודש", "word"),
    ("רוה״ק", "רוח הקודש", "word"),
    ("אעפ״כ", "אף על פי כן", "word"),
    ("אע״פ", "אף על פי", "word"),
    ("זא״ז", "זה את זה", "word"),
    ("עכ״פ", "על כל פנים", "word"),
    ("אח״כ", "אחר כך", "word"),
    ("ב״ד", "בית דין", "word"),
    ("ק״ק", "קודש קדשים", "word"),
    ("בהמ״ק", "בית המקדש", "word"),
    ("חז״ל", "חכמינו זכרונם לברכה", "word"),
    ("שנא׳", "שנאמר", "word"),
    ("פי׳", "פירוש", "word"),
    ("ית׳", "יתברך", "word"),
    ("הי׳", "היה", "word"),
    ("יהי׳", "יהיה", "word"),
    ("תהי׳", "תהיה", "word"),
    ("כו׳", "כולי", "word"),
    ("מל׳", "מלשון", "word"),
    ("וי״ו", "ויו", "word"),         # letter names
    ("נו״ן", "נון", "word"),
    ("כ״ף", "כף", "word"),
    ("למ״ד", "למד", "word"),
]

# AB-CTX (OPEN-ladder 13, the rule mends of 2026-11-25; stage 58's table): rows that write an abbreviation otherwise
# in one context. (abbrev, context, written). The contexts, as ladder_banks.context_of() reads them:
#   after_makom        the token before ends in מקום (המקום, למקום, שהמקום): ב״ה is ברוך הוא, not בית המקדש
#   after_negation     a negation (לא, אין, אינו, בל, ...) among the six tokens before, in the same sentence (no
#                      token ending in `:` or `.` between): כ״א is כי אם, not כל אחד
#   to_idol_possessive the token has the prefix ל (or the token before is אל / ואל) and the next token is a possessive
#                      (של...): עכו״ם is עבודת כוכבים (an idol), not עובדי כוכבים ומזלות (idolaters); the article
#                      prefix ה is dropped there (a construct form: אל העכו״ם שלו -> אל עבודת כוכבים שלו)
CONTEXT = [
    ("ב״ה", "after_makom", "ברוך הוא"),
    ("כ״א", "after_negation", "כי אם"),
    ("עכו״ם", "to_idol_possessive", "עבודת כוכבים"),
]
NEGATIONS = ("לא", "ולא", "שלא", "אין", "ואין", "שאין", "אינו", "אינה", "אינם", "אינן", "אינך", "אינני", "איננו",
             "בל", "בלי", "בלתי")                 # not אל: in these comments mostly the preposition


def context_rows():
    return list(CONTEXT)


UNITS = "אבגדהוזחט"
TENS = "יכלמנסעפצ"
LETTERS = "אבגדהוזחטיכלמנסעפצקרשת"


def numbers():
    out = [(x + "׳", x + "׳", "number") for x in LETTERS]
    for t in TENS:
        for u in UNITS:
            if t == "י" and u in "הו":
                continue
            if t == "כ" and u == "א":
                continue
            out.append((t + "״" + u, t + "״" + u, "number"))
    out += [("ט״ו", "ט״ו", "number"), ("ט״ז", "ט״ז", "number")]
    return out


def rows():
    """the whole table, in its fixed order: head, added, numbers"""
    seen, out = set(), []
    named = {r[0] for r in HEAD + ADDED}
    for r in HEAD + ADDED + [x for x in numbers() if x[0] not in named]:   # ה׳ is the divine name, not 5
        if r[0] in seen:
            raise ValueError("duplicate abbreviation row " + r[0])
        seen.add(r[0]); out.append(r)
    return out
