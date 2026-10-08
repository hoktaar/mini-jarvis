"""Bestätigungen: ja / nein / nochmal / unklar – streng statt wohlwollend.

Ein „Ja“ zählt nur, wenn die Antwort kurz ist, mit einem Ja-Wort beginnt und keine
Verneinung enthält. „Wie bitte?“ oder ein Satz aus dem Fernseher bestätigen nichts.
"""

from __future__ import annotations

import re
from enum import Enum

from pipecat.classifiers.base_classifier import BaseClassifier, YesNoQuestion


class Answer(str, Enum):
    YES = "yes"
    NO = "no"
    REPEAT = "repeat"
    UNCLEAR = "unclear"


YES_WORDS = {"ja", "jawohl", "jap", "jep", "jo", "genau", "klar", "okay", "ok", "okey", "bestätigt",
             "bestätige", "richtig", "gerne", "sicher", "mach", "machs", "los", "yes", "positiv", "korrekt"}
NO_WORDS = {"nein", "nee", "nö", "ne", "stopp", "stop", "abbrechen", "abbruch", "lass", "nicht", "falsch",
            "halt", "warte", "vergiss", "negativ", "niemals", "no", "keinesfalls", "später", "kein", "keine"}
# Nach dem Ja-Wort sind nur noch bekräftigende Wörter erlaubt – sonst ist es ein anderer Satz.
AFFIRM = YES_WORDS | {"bitte", "das", "es", "so", "danke", "tu", "doch", "auf", "jeden", "fall", "natürlich",
                      "absolut", "weiter", "gern", "schon", "sofort", "jetzt", "ausführen", "machen"}
FILLER = {"äh", "ähm", "öhm", "hm", "also", "jarvis", "hey", "na"}
REPEAT_RE = re.compile(r"^(wie\s+bitte|was|bitte|nochmal|noch\s+mal|wiederhol\w*|wie|hä|was\s+hast\s+du\s+gesagt)\b")

QUESTION = YesNoQuestion(
    instructions="Stimmt die Person der vorgeschlagenen Aktion eindeutig zu?",
    yes="eindeutiges Ja, z. B. 'ja', 'mach das', 'bestätigt'",
    no="Ablehnung, Zögern oder Abbruch",
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zäöüß']+", text.lower())


def strict_yes_no(text: str) -> float:
    """Wahrscheinlichkeit für „ja“ nach festen Regeln (0,97 / 0,03 / 0,5)."""
    words = [w for w in _words(text) if w not in FILLER]
    if not words:
        return 0.5
    if any(w in NO_WORDS for w in words):
        return 0.03
    if words[0] in YES_WORDS and len(words) <= 5 and all(w in AFFIRM for w in words[1:]):
        return 0.97
    return 0.5


def is_repeat_request(text: str) -> bool:
    return bool(REPEAT_RE.match(text.lower().strip(" ,.!?")))


async def classify_confirmation(classifier: BaseClassifier, text: str, threshold: float = 0.9) -> Answer:
    if is_repeat_request(text) and strict_yes_no(text) == 0.5:
        return Answer.REPEAT
    result = (await classifier.yes_no(text, {"confirm": QUESTION}))["confirm"]
    if result.probability >= threshold:
        return Answer.YES
    if result.probability <= 1 - threshold:
        return Answer.NO
    return Answer.UNCLEAR
