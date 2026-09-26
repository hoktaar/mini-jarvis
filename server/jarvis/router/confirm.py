"""Bestätigungen: ja / nein / unklar – mit Schwelle statt Wohlwollen."""

from __future__ import annotations

from enum import Enum

from pipecat.classifiers.base_classifier import BaseClassifier, YesNoQuestion


class Answer(str, Enum):
    YES = "yes"
    NO = "no"
    UNCLEAR = "unclear"


QUESTION = YesNoQuestion(
    instructions="Stimmt die Person der vorgeschlagenen Aktion eindeutig zu?",
    yes="eindeutiges Ja, z. B. 'ja', 'mach das', 'bestätigt'",
    no="Ablehnung, Zögern oder Abbruch",
)


async def classify_confirmation(classifier: BaseClassifier, text: str, threshold: float = 0.9) -> Answer:
    result = (await classifier.yes_no(text, {"confirm": QUESTION}))["confirm"]
    if result.probability >= threshold:
        return Answer.YES
    if result.probability <= 1 - threshold:
        return Answer.NO
    return Answer.UNCLEAR
