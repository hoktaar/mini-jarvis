import time

from jarvis.app import build_services
from jarvis.devices import DeviceRegistry
from jarvis.mcp_servers.docker_mcp import check_allowed
from jarvis.session import JarvisSession
from jarvis.tools.timers import TimerService


def test_devices(tmp_path):
    from jarvis.db import Database

    reg = DeviceRegistry(Database(tmp_path / "t.db"))
    dev, token = reg.create("Küche", "cyd", "Küche")
    assert reg.verify(token).id == dev.id
    assert reg.verify("falsch") is None
    reg.revoke(dev.id)
    assert reg.verify(token) is None


async def test_timers_fire(tmp_path):
    from jarvis.db import Database

    fired = []

    async def notify(row):
        fired.append(row)

    ts = TimerService(Database(tmp_path / "t.db"), notify)
    ts.add("timer", time.time() - 1, "Pizza")
    ts.add("timer", time.time() + 3600, "später")
    await ts.check_due()
    assert [r["label"] for r in fired] == ["Pizza"]
    assert len(ts.active()) == 1


def test_whitelist():
    wl = {"jellyfin": {"status", "restart"}}
    assert check_allowed(wl, "jellyfin", "restart") is None
    assert check_allowed(wl, "jellyfin", "stop")
    assert check_allowed(wl, "plex", "status")


async def test_session_confirm_flow(config_dir, tmp_path):
    s = build_services(config_dir, tmp_path, tmp_path / "j.db")
    dev, _ = s.devices.create("Test", "test")
    sess = JarvisSession(s, dev)
    r = await sess.execute("container_action", {"name": "jellyfin", "action": "restart"})
    assert r.data.get("needs_confirmation") and sess.pending is not None
    r = await sess.execute("set_timer", {"duration": 60})
    assert r.ok and "Minute" in r.speech
    assert (await sess.execute("get_time", {})).ok
