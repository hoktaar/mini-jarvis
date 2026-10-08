"""Hilfen für Geräte-WebSockets im TestClient."""

import time


def disconnect(ws, services, timeout: float = 5.0) -> None:
    """Verbindung trennen und warten, bis der Server die Sitzung beendet hat.

    Beim Verlassen des with-Blocks bricht der TestClient den Server-Task sofort ab. Trifft das
    die Pipeline mitten im Herunterfahren, kommt ein CancelledError im Test an – deshalb zuerst
    sauber trennen und das Sitzungsende abwarten.
    """
    ws.close()
    deadline = time.monotonic() + timeout
    while any(s.voice is not None for s in services.sessions.values()):
        if time.monotonic() > deadline:
            raise AssertionError("Sitzung endet nach dem Trennen nicht")
        time.sleep(0.01)
