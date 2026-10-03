import asyncio

from orbit_backend.services.events import EventBus


def test_old_process_cursor_resyncs_and_replays_new_events():
    async def run():
        bus = EventBus()
        bus.publish("data", "changed", {"revision": 1})
        frames, gap = bus.since(500, {"data"})
        assert gap and [f.id for f in frames] == [1]
        stream = bus.stream(500, {"data"})
        try:
            assert b"retry:" in await anext(stream)
            assert b"server_restart" in await anext(stream)
            assert b"id: 1" in await asyncio.wait_for(anext(stream), 1)
        finally:
            await stream.aclose()
    asyncio.run(run())


def test_event_after_empty_restart_resync_is_not_skipped():
    async def run():
        bus = EventBus()
        stream = bus.stream(500, {"data"})
        try:
            await anext(stream)
            assert b"server_restart" in await anext(stream)
            bus.publish("data", "changed", {"revision": 1})
            assert b"id: 1" in await asyncio.wait_for(anext(stream), 1)
        finally:
            await stream.aclose()
    asyncio.run(run())
