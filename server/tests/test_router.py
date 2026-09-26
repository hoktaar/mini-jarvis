import pytest

from jarvis.config import RouterCfg
from jarvis.router.classifier import LocalExampleClassifier
from jarvis.router.confirm import Answer, classify_confirmation
from jarvis.router.router import Route, Router, load_intents


@pytest.fixture
def router(intents_data):
    intents = load_intents(intents_data)
    clf = LocalExampleClassifier({n: i.examples for n, i in intents.items()})
    return Router(intents, clf, RouterCfg(), known_names=["jellyfin", "nextcloud"])


@pytest.mark.parametrize("text,intent", [
    ("Wie spät ist es?", "time_now"),
    ("Stell einen Timer auf zehn Minuten", "timer_set"),
    ("Wie wird das Wetter morgen?", "weather"),
    ("Starte den Jellyfin Container neu", "docker_action"),
])
async def test_intents(router, text, intent):
    d = await router.decide(text)
    assert d.intent == intent


async def test_fast_path_with_slot(router):
    d = await router.decide("Stell einen Timer auf fünf Minuten")
    assert d.route == Route.FAST
    assert d.slots["duration"] == 300


async def test_missing_slot_asks(router):
    d = await router.decide("Stell einen Timer")
    assert d.route in (Route.ASK_SLOT, Route.FOCUSED)


async def test_critical_fast_extracts_slots(router):
    # Schnellweg darf kritische Absichten erkennen – ausgeführt wird erst nach Bestätigung (Policy).
    d = await router.decide("Starte den Jellyfin Container neu")
    assert d.route == Route.FAST
    assert d.slots == {"name": "jellyfin", "action": "restart"}


async def test_unknown_container_asks(router):
    d = await router.decide("Starte den Lüffin Container neu")
    assert d.route == Route.ASK_SLOT


async def test_escalation(router):
    d = await router.decide("Denk gründlich nach: was ist der Sinn des Lebens?")
    assert d.route == Route.ESCALATE


@pytest.mark.parametrize("text,answer", [
    ("Ja, mach das", Answer.YES),
    ("Nein", Answer.NO),
    ("Bitte nicht", Answer.NO),
    ("Mhm", Answer.UNCLEAR),
])
async def test_confirmation(text, answer):
    clf = LocalExampleClassifier({"x": ["x"]})
    assert await classify_confirmation(clf, text) == answer
