"use strict";

// Trust boundary: do not serialize a collector-supplied timing object as-is.
// Fixed primitive allowlist, cross-field arithmetic and strict upper bounds.
const MAX_MS = 180000, MAX_RX = 1048576;
const values = (x, keys) => x && typeof x === "object" && !Array.isArray(x) &&
  Object.keys(x).sort().join() === [...keys].sort().join();
const requireFact = x => {if (!x) throw Error("invalid_public_timeline");};
const integer = (v, maximum = MAX_RX) =>
  Number.isSafeInteger(v) && v >= 0 && v <= maximum;
const maybe = (v, max = MAX_MS) => v === null || integer(v, max);
const oneOf = (v, a) => typeof v === "string" && a.includes(v);
const TX = ["open_client", "pong_before_open", "read_v4_h2", "pong_h2"];
const FRAMES = ["ping_h2", "response_h2", "notification_h2"];
const READ = ["received", "eof", "cancelled_read", "read_error"];

function validate(t, rxBytes, readCalls) {
  requireFact(values(t, ["basis", "reads", "tx", "h2_candidates", "unattributed",
    "close", "fragmented_candidates", "concatenated_reads"]));
  requireFact(t.basis === "client_monotonic_relative" && integer(rxBytes) &&
    integer(readCalls, 260) && Array.isArray(t.reads) && t.reads.length === readCalls &&
    Array.isArray(t.tx) && t.tx.length <= 100 &&
    Array.isArray(t.h2_candidates) && t.h2_candidates.length <= 256 &&
    Array.isArray(t.unattributed) && t.unattributed.length <= 1);
  let offset = 0, previous = null;
  for (let i = 0; i < t.reads.length; i++) {
    const r = t.reads[i];
    requireFact(values(r, ["index", "offset", "requested", "received",
      "started_ms", "ended_ms", "duration_ms", "gap_previous_ms",
      "since_last_tx_ms", "state"]) &&
      r.index === i && r.offset === offset &&
      integer(r.requested, 4096) && r.requested > 0 &&
      integer(r.received, r.requested) &&
      integer(r.started_ms, MAX_MS) && integer(r.ended_ms, MAX_MS) &&
      r.ended_ms >= r.started_ms &&
      r.duration_ms === r.ended_ms - r.started_ms &&
      r.gap_previous_ms === (previous === null ? null : r.started_ms - previous) &&
      (previous === null || r.started_ms >= previous) &&
      maybe(r.since_last_tx_ms) &&
      (r.since_last_tx_ms === null || r.since_last_tx_ms <= r.started_ms) &&
      oneOf(r.state, READ) && (r.state === "received") === (r.received > 0));
    offset += r.received;
    previous = r.ended_ms;
  }
  requireFact(offset === rxBytes);
  const completedTx = [];
  for (const tx of t.tx) {
    requireFact(values(tx, ["category", "started_ms", "ended_ms", "duration_ms"]) &&
      oneOf(tx.category, TX) && integer(tx.started_ms, MAX_MS) &&
      maybe(tx.ended_ms) && maybe(tx.duration_ms) &&
      (tx.ended_ms === null) === (tx.duration_ms === null) &&
      (tx.ended_ms === null ||
       (tx.ended_ms >= tx.started_ms &&
        tx.duration_ms === tx.ended_ms - tx.started_ms)));
    if (tx.ended_ms !== null) completedTx.push(tx.ended_ms);
  }
  const sinceLast = time => {
    const past = completedTx.filter(v => v <= time);
    return past.length ? time - Math.max(...past) : null;
  };
  for (const r of t.reads)
    requireFact(r.since_last_tx_ms === sinceLast(r.started_ms));
  let priorPing = null, fragmented = 0;
  for (const f of t.h2_candidates) {
    requireFact(values(f, ["kind", "confidence", "offset", "length",
      "completed_ms", "first_read", "last_read", "since_last_tx_ms",
      "ping_interval_ms"]) &&
      oneOf(f.kind, FRAMES) && f.confidence === "h2_hypothesis_only" &&
      integer(f.offset) && integer(f.length) && f.length > 0 &&
      f.offset + f.length <= rxBytes && integer(f.completed_ms, MAX_MS) &&
      maybe(f.since_last_tx_ms) && maybe(f.ping_interval_ms));
    const overlapping = t.reads.filter(r => r.offset < f.offset + f.length &&
      r.offset + r.received > f.offset).map(r => r.index);
    requireFact(overlapping.length > 0 && f.first_read === overlapping[0] &&
      f.last_read === overlapping.at(-1) &&
      f.since_last_tx_ms === sinceLast(f.completed_ms) &&
      f.ping_interval_ms === (f.kind === "ping_h2" && priorPing !== null ?
        f.completed_ms - priorPing : null));
    if (f.kind === "ping_h2") priorPing = f.completed_ms;
    if (f.last_read > f.first_read) fragmented++;
  }
  for (const u of t.unattributed) {
    requireFact(values(u, ["offset", "length", "basis"]) &&
      integer(u.offset) && integer(u.length) && u.length > 0 &&
      u.offset + u.length <= rxBytes &&
      oneOf(u.basis, ["h2_unproven_suffix", "unclassified"]));
  }
  const close = t.close;
  requireFact(values(close, ["state", "started_ms", "ended_ms", "duration_ms"]) &&
    oneOf(close.state, ["not_recorded", "attempted", "closed", "error"]) &&
    maybe(close.started_ms) && maybe(close.ended_ms) && maybe(close.duration_ms) &&
    (close.state === "not_recorded") === (close.started_ms === null) &&
    (["closed", "error"].includes(close.state)) === (close.ended_ms !== null) &&
    (close.ended_ms === null ? close.duration_ms === null :
      (close.ended_ms >= close.started_ms &&
       close.duration_ms === close.ended_ms - close.started_ms)));
  const concatenated = t.reads.filter(r => t.h2_candidates.filter(f =>
    f.first_read <= r.index && r.index <= f.last_read).length >= 2).length;
  requireFact(t.fragmented_candidates === fragmented &&
    t.concatenated_reads === concatenated);
  return t;
}
module.exports = {validate};
