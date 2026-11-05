"""R5 v2, bounded per-generation facts. No HA imports, packets or policy."""

from scripts.campaign_runtime_contract import integer, keys, need

RECOVERABLE = {"eof", "timeout", "transport", "tls", "close_client"}
OUTCOMES = {
    "not_exercised",
    "no_disconnect",
    "reopen_failed",
    "stability_lost",
    "verified",
    "timeout",
    "internal",
    "closed",
}


def is_multi(e):
    return type(e.get("recovery")) is dict and "schema" in e["recovery"]


def validate(e):
    from scripts.ha_campaign_evidence import empty_recovery

    r, w, final = e["recovery"], e["window"], e["cleanup"]["observation"]
    keys(r, set(empty_recovery()) | {"schema", "generations", "diagnostic"})
    need(type(r["schema"]) is int and r["schema"] == 2)
    need(r["mode"] == "pong_inhibition_after_120s" and r["boundary_proven"] is False)
    need(type(r["outcome"]) is str and r["outcome"] in OUTCOMES)
    for name in ("accepted_at_ms", "loss_after_ms", "reopened_after_ms"):
        need(r[name] is None or integer(r[name], 0, 600000))
    for name in ("loss_generation", "read_generation"):
        need(r[name] is None or integer(r[name], 1, 3))
    need(r["read_sequence"] is None or integer(r["read_sequence"], 1, 6))
    for name in ("suppressed_pongs", "recovery_pongs"):
        need(integer(r[name], 0, 1048576))
    need(integer(r["stable_ms"], 0, 120000))
    keys(r["diagnostic"], {"interruption", "cleanup"})
    for slot, value in r["diagnostic"].items():
        if value is None:
            continue
        keys(
            value,
            {"category", "owner", "generation", "inhibition_exercised", "subcode"},
        )
        need(
            type(value["category"]) is str
            and value["category"]
            in RECOVERABLE | {"closed", "cancelled", "internal", "protocol"}
        )
        need(
            type(value["owner"]) is str
            and value["owner"]
            in (
                {"transport_close", "observer_cleanup"}
                if slot == "cleanup"
                else {"transport_read", "transport_write", "opening", "session"}
            )
        )
        need(
            integer(value["generation"], 1, 3)
            and type(value["inhibition_exercised"]) is bool
        )
        need(
            integer(value["subcode"], 0, 255)
            if value["category"] == "close_client"
            else value["subcode"] is None
        )
    need(r["diagnostic"]["interruption"] is None or r["outcome"] != "verified")
    need(
        r["diagnostic"]["cleanup"] is None
        or final["cleanup_failed"]
        or not e["cleanup"]["completed"]
    )
    rows = r["generations"]
    need(type(rows) is list and len(rows) <= 3 and len(rows) == final["attempts"])
    for index, row in enumerate(rows, 1):
        keys(
            row,
            {
                "generation",
                "connect_ms",
                "opened_ms",
                "loss_ms",
                "category",
                "subcode",
                "cleanup_ms",
                "pongs",
            },
        )
        need(type(row["generation"]) is int and row["generation"] == index)
        for name in ("connect_ms", "opened_ms", "loss_ms", "cleanup_ms"):
            need(row[name] is None or integer(row[name], 0, 600000))
            if e.get("diagnostic_schema") == 1 and row[name] is not None:
                need(row[name] <= e["diagnostic"]["end_ms"])
        need(integer(row["pongs"], 0, 1048576))
        need(
            row["category"] is None
            or type(row["category"]) is str
            and row["category"] in RECOVERABLE
        )
        need((row["loss_ms"] is None) == (row["category"] is None))
        need(
            integer(row["subcode"], 0, 255)
            if row["category"] == "close_client"
            else row["subcode"] is None
        )
        if row["opened_ms"] is not None:
            need(
                row["connect_ms"] is not None
                and row["connect_ms"] <= row["opened_ms"] <= w["elapsed_ms"]
            )
        if row["loss_ms"] is not None:
            need(
                row["opened_ms"] is not None
                and row["opened_ms"] <= row["loss_ms"] <= w["elapsed_ms"]
            )
        if row["cleanup_ms"] is not None:
            need(row["connect_ms"] is None or row["cleanup_ms"] >= row["connect_ms"])
            need(row["loss_ms"] is None or row["cleanup_ms"] >= row["loss_ms"])
        if index > 1 and row["connect_ms"] is not None:
            old = rows[index - 2]
            need(
                old["loss_ms"] is not None
                and old["cleanup_ms"] is not None
                and old["cleanup_ms"] <= row["connect_ms"]
            )
    if r["outcome"] != "verified":
        return False
    # A SUCCESS needs both the scoped observer and independently tapped F1
    # ownership facts. F1 is validated separately by the enclosing contract.
    need(e.get("diagnostic_schema") == 1)
    d, o = e["diagnostic"], w["observation"]
    need(2 <= len(rows) <= 3 and len(d["owners"]) == len(rows))
    need(d["first"] is not None and d["first"][3] in RECOVERABLE)
    final_failed = not e["cleanup"]["completed"] or final["cleanup_failed"]
    if final_failed:
        need(
            not e["completed"] and e["terminal"] in {"unexpected", "timeout", "closed"}
        )
        need(d["terminal"] is None or d["terminal"][4] == "cleanup")
    else:
        need(d["terminal"] is None and d["cleanup"] is None)
        need(e["completed"] and e["terminal"] == "none")
    need(w["active"] and o is not None and not o["stopped"] and not o["cleanup_failed"])
    need(final_failed or final["stopped"] and final["cleaned_generation"] == len(rows))
    need(
        o["generation"]
        == o["read_generation"]
        == final["generation"]
        == r["read_generation"]
        == len(rows)
    )
    need(o["loss_generation"] == final["loss_generation"])
    need(o["read_sequence"] == final["read_sequence"] == r["read_sequence"])
    need(r["stable_ms"] == 120000 and r["suppressed_pongs"] > 0)
    need(rows[-1]["loss_ms"] is None and rows[-1]["pongs"] == r["recovery_pongs"] > 0)
    need(
        rows[-1]["opened_ms"] is not None
        and rows[-1]["opened_ms"] + 120000 <= w["elapsed_ms"]
    )
    control = r["loss_generation"]
    need(type(control) is int and control == 1)
    first, following = rows[control - 1], rows[control]
    need(first["category"] in {"eof", "close_client"})
    need(r["accepted_at_ms"] == first["opened_ms"])
    need(r["loss_after_ms"] is not None and r["reopened_after_ms"] is not None)
    need(120000 <= r["loss_after_ms"] < r["reopened_after_ms"] < 240000)
    need(first["loss_ms"] == first["opened_ms"] + r["loss_after_ms"])
    need(following["opened_ms"] == first["opened_ms"] + r["reopened_after_ms"])
    for index, (row, owner) in enumerate(zip(rows, d["owners"], strict=True), 1):
        need(row["opened_ms"] is not None)
        need(
            owner["role"] == "a"
            and owner["generation"] == owner["accepted_generation"] == index
            and owner["accepted"]
        )
        if index < len(rows) or not final_failed:
            need(
                row["cleanup_ms"] is not None
                and owner["stage"] == "reaped"
                and owner["pending"] == 0
                and owner["close"][3] is not None
            )
        need(owner["close_client_subcode"] == row["subcode"])
        if index < len(rows):
            need(row["loss_ms"] is not None)
            need(row["category"] != "close_client" or row["subcode"] in {3, 6})
        good = [
            s
            for s in e["samples"]
            if s["decoded"] and s["observation"]["read_generation"] == index
        ]
        # Every accepted generation must have a new correlated acquisition;
        # skipping an intermediate generation cannot be repaired by the last.
        need(bool(good) and owner["last_read"] is not None)
        for seq, sample in enumerate(good, 1):
            so = sample["observation"]
            need(
                sample["available"]
                and sample["error"] == "none"
                and so["read_sequence"] == seq
            )
            need(
                row["opened_ms"] <= sample["at_ms"]
                and (row["loss_ms"] is None or sample["at_ms"] <= row["loss_ms"])
            )
            need(not so["stopped"] and not so["cleanup_failed"])
            if index > 1:
                old = rows[index - 2]
                need(so["cleaned_generation"] == index - 1)
                if old["category"] == "timeout":
                    prior = next(
                        s["observation"]
                        for s in reversed(e["samples"])
                        if s["decoded"]
                        and s["observation"]["read_generation"] == index - 1
                    )
                    for name in (
                        "loss_generation",
                        "loss_kind",
                        "close_client_subcode",
                    ):
                        need(so[name] == prior[name])
                else:
                    need(so["loss_generation"] == index - 1)
                    need(
                        so["loss_kind"]
                        == (
                            "close_client"
                            if old["category"] == "close_client"
                            else "transport"
                        )
                    )
                    need(so["close_client_subcode"] == old["subcode"])
        need(owner["last_read"][0] == good[-1]["observation"]["read_sequence"])
    last = e["samples"][-1]
    need(last["decoded"] and last["observation"]["read_generation"] == len(rows))
    for name in ("loss_generation", "loss_kind", "close_client_subcode"):
        need(o[name] == last["observation"][name] == final[name])
    # A failed read may be followed by a proved fresh read, never replayed or
    # credited using B7's available old snapshot.
    for sample in e["samples"]:
        if not sample["decoded"]:
            need(sample["error"] in {"transport", "timeout", "closed"})
            need(
                any(
                    s["ordinal"] > sample["ordinal"]
                    and s["decoded"]
                    and s["observation"]["read_generation"]
                    > sample["observation"]["generation"]
                    for s in e["samples"]
                )
            )
    return True
