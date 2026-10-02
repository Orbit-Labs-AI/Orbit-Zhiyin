"""Select Codex's active history before mapping; discarded bytes remain in L0/L1."""

import re
from collections import defaultdict
from pathlib import Path


def prepare_history(store, infos, mappers):
    """Resolve active rollout chains and legacy rollback without copying staging facts."""
    groups, active_paths = defaultdict(list), {}
    for info in infos:
        mapper = mappers.get(info["file_id"])
        if info["agent"] != "codex" or mapper is None:
            continue
        mapper.excluded_records = {}
        if info["role"] == "index_db":
            for record in store.iter_file(info["file_id"]):
                payload = record.data.get("payload", {})
                if record.data.get("type") == "state_index" and payload.get("rollout_path"):
                    active_paths[info["source_id"], str(payload.get("id"))] = payload[
                        "rollout_path"
                    ]
        elif mapper.header.get("id"):
            groups[info["source_id"], str(mapper.header["id"])].append(info)

    ranks = {}
    for key, files in groups.items():
        aliases, parents = {}, {}
        for info in files:
            stem = Path(info["relative_path"]).name.removesuffix(".zst").removesuffix(".jsonl")
            ids = re.findall(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", stem)
            aliases[ids[-1] if ids else stem.removeprefix("rollout-")] = info["file_id"]
        for info in files:
            base = mappers[info["file_id"]].header.get("history_base") or {}
            parent = aliases.get(str(base.get("thread_id")))
            if parent and parent != info["file_id"]:
                parents[info["file_id"]] = parent
        bounds = None
        if parents:
            current = next(
                (
                    f["file_id"]
                    for f in files
                    if Path(f["relative_path"]).name == Path(active_paths.get(key, "")).name
                ),
                None,
            )
            if current is None:
                sinks = [f for f in files if f["file_id"] not in set(parents.values())]
                current = max(sinks or files, key=lambda f: f["relative_path"])["file_id"]
                if len(sinks) > 1:
                    store.issue(key[0], "active_history_inferred", detail={"session": key[1]})
            bounds, limit = {}, float("inf")
            while current and current not in bounds:
                bounds[current] = limit
                base = mappers[current].header.get("history_base") or {}
                end = base.get("end_ordinal_exclusive")
                if isinstance(end, int) and not isinstance(end, bool):
                    limit = min(limit, end)
                current = parents.get(current)
            for rank, file_id in enumerate(reversed(bounds)):
                ranks[file_id] = rank
        # Exact archived/moved copies share one projection, with both captures retained.
        seen = set()
        for info in sorted(
            files, key=lambda f: (f["status"] == "gone_upstream", f["relative_path"])
        ):
            mapper = mappers[info["file_id"]]
            fingerprint = tuple(
                mapper.record_signature(r) for r in store.iter_file(info["file_id"])
            )
            duplicate = fingerprint in seen
            seen.add(fingerprint)
            starts, previous = [], []
            for record in store.iter_file(info["file_id"]):
                ordinal = record.data.get("ordinal", record.ordinal)
                if duplicate or bounds is not None and ordinal >= bounds.get(info["file_id"], -1):
                    mapper.excluded_records[record.record_uid] = (
                        "duplicate_rollout"
                        if duplicate
                        else "reverted_history:outside_active_chain"
                    )
                    continue
                payload = record.data.get("payload") or {}
                typ = payload.get("type")
                if record.data.get("type") == "event_msg":
                    if typ in ("task_started", "turn_started"):
                        starts.append({"position": len(previous), "human": False})
                    if (
                        typ == "user_message"
                        or typ == "item_completed"
                        and (payload.get("item") or {}).get("type") == "UserMessage"
                    ):
                        if not starts or starts[-1]["human"] and typ == "user_message":
                            starts.append({"position": len(previous), "human": True})
                        else:
                            starts[-1]["human"] = True
                    if typ == "thread_rolled_back":
                        count = payload.get("num_turns")
                        humans = [s for s in starts if s["human"]]
                        if (
                            isinstance(count, int)
                            and not isinstance(count, bool)
                            and count > 0
                            and humans
                        ):
                            cut = humans[max(0, len(humans) - count)]["position"]
                            for uid in previous[cut:]:
                                mapper.excluded_records[uid] = "reverted_history:legacy_rollback"
                            starts = [s for s in starts if s["position"] < cut]
                previous.append(record.record_uid)
    return ranks
