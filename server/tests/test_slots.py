from datetime import datetime

from jarvis.router.slots import match_name, parse_action, parse_datetime, parse_duration


def test_durations():
    assert parse_duration("Timer auf fünf Minuten") == 300
    assert parse_duration("eine halbe Stunde") == 1800
    assert parse_duration("2 Stunden 10 Minuten") == 7800
    assert parse_duration("1,5 Stunden") == 5400
    assert parse_duration("Stell einen Timer") is None


def test_datetime():
    now = datetime(2026, 9, 26, 12, 0)
    assert parse_datetime("Weck mich morgen um sieben", now) == datetime(2026, 9, 27, 7, 0)
    assert parse_datetime("um 6:30", now) == datetime(2026, 9, 27, 6, 30)
    assert parse_datetime("heute um 18 Uhr", now) == datetime(2026, 9, 26, 18, 0)


def test_names():
    assert match_name("läuft jelly fin", ["jellyfin", "plex"]) == "jellyfin"
    assert match_name("status nextclod", ["nextcloud"]) == "nextcloud"
    assert match_name("wie ist das wetter", ["nextcloud"]) is None
    assert match_name("Starte den Jellyfin-Container neu", ["jellyfin"]) == "jellyfin"


def test_actions():
    assert parse_action("Starte Jellyfin neu") == "restart"
    assert parse_action("Stopp den Plex Container") == "stop"
    assert parse_action("Starte Nextcloud") == "start"
    assert parse_action("Wie ist das Wetter") is None
