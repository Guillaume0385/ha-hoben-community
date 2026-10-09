"""Offline private-capture replay for MANAGER, with no live execution mode."""

import argparse
import json
import math
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.boundary_analysis import RxRead, analyze_capture  # noqa: E402


def replay(directory: Path) -> dict:
    """Validate journal coverage, preserve original times and replay H2 chunkings."""
    raw = (directory / "rx.bin").read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError("Invalid private capture")
    reads = []
    offset = 0
    previous = None
    accepted_offset = None
    with (directory / "journal.jsonl").open() as journal:
        for line in journal:
            record = json.loads(line)
            if record.get("kind") == "opening_accepted":
                accepted = record["offset"]
                read_index = record["read_index"]
                received_at = record["received_at"]
                if (
                    accepted_offset is not None
                    or type(accepted) is not int
                    or not 0 <= accepted <= offset - 48
                    or type(read_index) is not int
                    or read_index != len(reads) - 1
                    or type(received_at) not in (int, float)
                    or not math.isfinite(received_at)
                    or received_at != previous
                ):
                    raise ValueError("Invalid private opening acceptance")
                accepted_offset = accepted
                continue
            if record.get("kind") != "rx":
                continue
            fields = (
                record["index"],
                record["offset"],
                record["requested"],
                record["returned"],
            )
            started, ended = record["started"], record["ended"]
            if any(type(v) is not int for v in fields) or (
                fields[0] != len(reads)
                or fields[1] != offset
                or not 0 <= fields[3] <= fields[2] <= 4096
                or not all(
                    type(v) in (float, int) and math.isfinite(v)
                    for v in (started, ended)
                )
                or ended < started
                or (previous is not None and started < previous)
            ):
                raise ValueError("Invalid private journal")
            reads.append(RxRead(*fields, started, ended, previous))
            previous = ended
            offset += fields[3]
    if offset != len(raw):
        raise ValueError("Incomplete private journal")
    opening_offset = 0
    while opening_offset < len(raw) and raw[opening_offset] == 0x0A:
        opening_offset += 1
    if opening_offset == len(raw) or raw[opening_offset] != 0x04:
        opening_offset = None
    if accepted_offset is not None and accepted_offset != opening_offset:
        raise ValueError("Inconsistent private opening acceptance")
    return {
        "boundary_proven": False,
        **analyze_capture(
            raw,
            reads,
            opening_offset,
            prefix_accepted=accepted_offset is not None,
        ),
    }


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "Invalid replay arguments; use --help.\n")


def main(argv: list[str] | None = None) -> int:
    """Write annotations separately; never dump bytes or paths in errors."""
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--session-directory", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        directory = args.session_directory.resolve(strict=True)
        if directory.is_relative_to(Path(__file__).resolve().parents[1]):
            raise ValueError("Captures must remain outside Git")
        report = replay(directory)
        fd = os.open(
            directory / "reanalysis.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "w") as output:
            json.dump(report, output)
        print("Offline annotations saved separately; boundary remains unproven.")
        return 0
    except Exception:
        print("Private capture unavailable or invalid.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
