"""Visible event history queries and presentation.

History filtering is separate from chronological replay and joins the bounded
cue journal to persisted observations without changing provider identities.
"""

import asyncio
import time

BACKGROUND_HISTORY_KINDS = frozenset({"ocean_swell", "storm_potential", "birdsong"})
HIDDEN_HISTORY_KINDS = frozenset({"lightning_flash"})


class HistoryView:
    """Assemble the dashboard history from storage and cue snapshots."""

    def __init__(self, store):
        self.store = store

    async def recent_events(self, hours, limit, cues, background_states, instruments_for_kind):
        """Return recently occurring or recently emitted stored events."""
        hours = float(hours)
        hours = max(0.05, min(24.0, hours))
        cutoff = time.time() - (hours * 3600.0)
        events = await asyncio.to_thread(
            self.store.recent_visible_events, cutoff,
            BACKGROUND_HISTORY_KINDS | HIDDEN_HISTORY_KINDS, limit
        )
        recent_cues = tuple(
            cue
            for cue in cues
            if cue["emitted_at"] >= cutoff
            and cue["event"]["kind"] not in BACKGROUND_HISTORY_KINDS
            and cue["event"]["kind"] not in HIDDEN_HISTORY_KINDS
        )
        event_keys = {(event.provider, event.event_id) for event in events}
        emitted_keys = {
            (cue["event"]["provider"], cue["event"]["event_id"])
            for cue in recent_cues
        }
        missing_events = await asyncio.to_thread(
            self.store.events_by_keys, emitted_keys - event_keys
        )
        events = (*events, *missing_events)
        emitted_instruments = {}
        for cue in recent_cues:
            key = (cue["event"]["provider"], cue["event"]["event_id"])
            instruments = emitted_instruments.setdefault(key, [])
            if cue["instrument"] not in instruments:
                instruments.append(cue["instrument"])
        emitted_times = {
            (cue["event"]["provider"], cue["event"]["event_id"]): cue["emitted_at"]
            for cue in recent_cues
        }
        history = []
        for event in events:
            item = event.as_dict()
            key = (event.provider, event.event_id)
            instruments = emitted_instruments.get(key)
            if instruments is None:
                instruments = list(dict.fromkeys(instruments_for_kind(event.kind)))
            item["instruments"] = instruments
            item["instrument"] = instruments[0] if instruments else "none"
            item["emitted_at"] = emitted_times.get(key)
            history.append(item)
        for state in background_states:
            event = state["event"]
            if event["timestamp"] < cutoff:
                continue
            item = dict(event)
            item["instruments"] = [state["instrument"]]
            item["instrument"] = state["instrument"]
            item["emitted_at"] = state["published_at"]
            history.append(item)
        history.sort(
            key=lambda item: (
                item["emitted_at"] is not None,
                item["emitted_at"] or item["timestamp"],
            ),
            reverse=True,
        )
        return tuple(history[:max(1, min(20000, int(limit)))])
