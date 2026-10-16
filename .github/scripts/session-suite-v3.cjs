"use strict";
// Structural projection only. The future producer must obtain the origin's
// consumption receipt and stop history; a final snapshot is not that receipt.
const contract = require("../../scripts/session_suite_v3_contract.json");
const need = v => { if (!v) throw Error("invalid_session_suite_report"); };
const nil = v => v === null;
const integer = (v, max) => Number.isSafeInteger(v) && v >= 0 && v <= max;
const exact = (v, expected) => need(v && typeof v === "object" && !Array.isArray(v) &&
  Object.keys(v).sort().join() === [...expected].sort().join());
function validateV3(r,p,provenance,limits,terminals,messages) {
  const expected = [...provenance,...Object.keys(limits),...Object.keys(contract),
    "schema","scenario","boundary_proven","result","terminal","read_slot",
    "failure_phase","failure_category","message_category","causal_ms"];
  exact(r,expected);
  need(r.schema === 3 && r.scenario === "session-reconnect-no-pong" && r.boundary_proven === false);
  need(provenance.every(k => r[k] === p[k]));
  need(["merge_sha","candidate_sha"].every(k => typeof r[k] === "string" && /^[0-9a-f]{40}$/.test(r[k])));
  need(r.run_attempt === 1 && ["run_id","pr_number"].every(k => integer(r[k],Number.MAX_SAFE_INTEGER) && r[k] > 0));
  for (const [k,max] of Object.entries(limits)) need(integer(r[k],max));
  need(terminals.has(r.terminal) && ["recovered_120s","inconclusive","interrupted","not_run"].includes(r.result));
  for (const [group,fields] of Object.entries(contract)) {
    exact(r[group],Object.keys(fields));
    for (const [k,spec] of Object.entries(fields)) {
      const v = r[group][k];
      if (spec[0] === "nullable_int") need(nil(v) || integer(v,spec[1]));
      else if (spec[0] === "bool") need(typeof v === "boolean");
      else need(typeof v === "string" && spec[1].includes(v));
    }
  }
  need(r.reconnections === Math.max(0,r.opens-1) && r.pongs+r.pongs_suppressed <= r.pings);
  need(r.reads_ok+r.reads_failed === r.reads && r.reads_ok <= r.responses && r.responses <= r.reads);
  need(r.rx_chunks_total <= r.rx_bytes_total && r.eofs_after_suppression <= r.peer_eofs && r.peer_eofs <= r.opens);
  need(r.recovery_reads_ok <= r.reads_ok && r.recovery_pongs <= r.pongs);
  const phase=r.failure_phase, category=r.failure_category, message=r.message_category, causal=r.causal_ms;
  need(messages.has(phase) && terminals.has(category) && messages.get(phase).includes(message));
  need(integer(r.read_slot,r.reads) && (nil(causal) || integer(causal,360000)));
  const hasT0=r.timing.t0_observed;
  need((phase === "none" || !hasT0) === nil(causal));
  need((phase === "none") === ["verified","first_not_admissible"].includes(category));
  if (phase === "none") need(r.read_slot === 0 && category === r.terminal);
  if (["frame_boundary","message_classification","request_correlation","response_validation"].includes(phase)) need(category === "protocol");
  if (phase === "tls_read") need(["transport","budget"].includes(category));
  if (phase === "pong_tx") need(["transport","protocol"].includes(category));
  if (phase === "teardown") need(category === "closed" && r.terminal === "closed");
  if (phase === "scheduled_read") need(r.read_slot > 0);
  const t=r.timing,q=r.quarantine,s=r.stability,d=r.rx_diagnostic,end=t.functional_end_ms;
  const deadlines = Object.keys(t).filter(k => k.endsWith("deadline_ms")).map(k => t[k]);
  const success=r.result === "recovered_120s", skipped=r.result === "not_run";
  need(success === (r.terminal === "verified") && skipped === (r.terminal === "first_not_admissible"));
  const nullTiming=Object.entries(contract.timing).filter(([,v]) => v[0] === "nullable_int").every(([k]) => nil(t[k]));
  if (skipped) need(Object.keys(limits).every(k => r[k] === 0) && !hasT0 && nullTiming && phase === "none");
  else if (!hasT0) {
    need(nullTiming && phase === "opening" && category === r.terminal && r.read_slot === 0 && r.opens >= 1 && !success);
    need(["timeout","budget","transport","protocol","internal","closed"].includes(r.terminal));
    need(Object.keys(limits).filter(k => !["duration_ms","opens","reconnections","rx_bytes_total","rx_chunks_total"].includes(k)).every(k => r[k] === 0));
  }
  else {
    need(!nil(end) && r.opens >= 1 && r.duration_ms >= end);
    need(deadlines.every(v => !nil(v) && end <= v) && (nil(causal) || causal <= end));
    need(r.reads <= Math.floor(end/60000)+1);
    if (!nil(causal)) need(r.read_slot <= Math.floor(causal/60000)+1);
  }
  const inhibition=t.inhibition_ms,entered=q.entered_ms,eof=q.eof_ms,consumed=q.consumed_ms,accepted=q.accepted_ms;
  need(!nil(inhibition) === (r.pongs_suppressed > 0));
  if (!nil(inhibition)) need(inhibition >= 120000 && inhibition <= end);
  need((q.outcome === "not_entered") === nil(entered));
  if (nil(entered)) {
    need(["eof_ms","consumed_ms","origin_generation","cleanup_ms","stop_ms","accepted_ms","accepted_generation"].every(k => nil(q[k])));
    need(q.eof_origin === "none" && q.receipt === "none" && q.stop === "none");
  } else {
    need(!nil(inhibition) && inhibition <= entered && entered <= end && q.origin_generation === 1);
    need(entered < Math.min(240000,...deadlines));
    need(phase === "message_classification" && category === "protocol" && message === "close_client" && causal === entered);
  }
  need(nil(eof) === (q.eof_origin === "none"));
  if (!nil(eof)) need(!nil(entered) && entered <= eof && eof <= end);
  const transportEof=!nil(eof) && q.eof_origin === "transport_read";
  if (r.eofs_after_suppression) need(!nil(inhibition));
  if (transportEof) need(r.eofs_after_suppression === 1);
  need(!nil(consumed) === (q.receipt === "valid_at_consumption") && !nil(consumed) === (q.outcome === "consumed"));
  if (!nil(consumed)) need(transportEof && entered < eof && eof <= consumed && consumed < Math.min(240000,...deadlines) && consumed <= end);
  if (["waiting","no_eof"].includes(q.outcome)) need(nil(eof) && q.receipt === "none" && q.stop === "none" && r.eofs_after_suppression === 0);
  if (q.outcome === "revoked") need(q.receipt === "revoked_before_consumption" && ["local_before_consumption","cancel_before_consumption"].includes(q.stop));
  if (q.receipt === "revoked_before_consumption") need(q.outcome === "revoked");
  if (q.receipt === "invalid") need(q.outcome === "refused");
  if (q.outcome === "expired") need(end >= Math.min(240000,...deadlines));
  if (q.outcome === "waiting") need(end < Math.min(240000,...deadlines));
  need((q.stop === "none") === nil(q.stop_ms));
  if (!nil(q.stop_ms)) {
    need(!nil(entered) && entered <= q.stop_ms && q.stop_ms <= end);
    if (["local_after_consumption","cancel_after_consumption"].includes(q.stop)) {
      // Historical execution order comes from the owner receipt, not equality.
      need(!nil(consumed) && consumed <= q.stop_ms);
    } else need(nil(consumed));
  }
  if (!nil(q.cleanup_ms)) need(!nil(consumed) && consumed <= q.cleanup_ms && q.cleanup_ms <= end);
  need(nil(accepted) === nil(q.accepted_generation));
  need(r.recovery_generation === (q.accepted_generation || 0));
  if (!nil(accepted)) {
    need(!nil(consumed) && consumed < accepted && accepted < Math.min(240000,...deadlines));
    need(q.accepted_generation >= 2 && q.accepted_generation <= r.opens);
    need(q.accepted_generation === r.opens);
    need(accepted+120000 <= Math.min(360000,...deadlines));
    need(!nil(q.cleanup_ms) && q.cleanup_ms <= accepted && (nil(q.stop_ms) || accepted <= q.stop_ms));
    need(s.start_ms === accepted && s.generation === q.accepted_generation);
  } else need(Object.keys(s).filter(k => k !== "interrupted").every(k => nil(s[k])) && s.interrupted === false);
  if (q.stop !== "none") {
    need(r.result === "interrupted");
    if (nil(accepted)) need(r.terminal === "closed");
    else need(r.terminal === "stability_lost" && s.interrupted && !nil(s.end_ms));
  }
  if (!nil(s.start_ms)) {
    need(!nil(accepted) && accepted <= end);
    if (!nil(s.end_ms)) need(accepted <= s.end_ms && s.end_ms <= end);
    if (!nil(s.end_ms) && !nil(q.stop_ms)) need(s.interrupted && s.end_ms <= q.stop_ms);
    need(r.stable_ms === (nil(s.end_ms) ? 0 : s.end_ms-accepted));
    for (const [key,count] of [["first_pong_ms","recovery_pongs"],["first_read_ok_ms","recovery_reads_ok"]]) {
      need(!nil(s[key]) === (r[count] > 0));
      if (!nil(s[key])) need(accepted <= s[key] && s[key] <= (nil(s.end_ms) ? end : s.end_ms));
    }
  } else need(r.stable_ms === 0 && r.recovery_reads_ok === 0 && r.recovery_pongs === 0);
  if (success) {
    need(!nil(consumed) && !nil(accepted) && s.interrupted === false);
    need(s.end_ms === accepted+120000 && s.end_ms <= end && s.end_ms < Math.min(...deadlines));
    need(r.stable_ms === 120000 && r.recovery_pongs > 0 && r.recovery_reads_ok > 0);
    need(r.peer_eofs === 1 && r.opens === q.accepted_generation && d.observed && d.end_ms === end);
    need(q.stop === "none");
  }
  if (r.terminal === "stability_lost") need(!nil(accepted) && s.interrupted);
  if (r.terminal === "not_exercised") need(nil(inhibition) && nil(entered));
  if (r.terminal === "no_disconnect") need(!nil(inhibition) && !transportEof && nil(consumed));
  if (!d.observed) {
    need(Object.entries(contract.rx_diagnostic).filter(([,v]) => v[0] === "nullable_int").every(([k]) => nil(d[k])));
    need(d.framer === "not_observed" && d.phase === "none" && d.category === "none" && d.message === "unclassified");
  } else {
    need(!nil(end) && d.start_ms === 150000 && !nil(d.end_ms) && 150000 <= d.end_ms && d.end_ms <= end);
    need(["bytes","chunks","start_offset","end_offset"].every(k => !nil(d[k])));
    need(d.start_offset <= d.end_offset && d.end_offset <= r.rx_bytes_total && d.end_offset-d.start_offset === d.bytes);
    need(d.chunks <= d.bytes && d.chunks <= r.rx_chunks_total && (d.bytes === 0) === (d.chunks === 0));
    need(nil(d.first_rx_ms) === (d.bytes === 0) && nil(d.last_rx_ms) === (d.bytes === 0));
    if (d.bytes) need(150000 <= d.first_rx_ms && d.first_rx_ms <= d.last_rx_ms && d.last_rx_ms <= d.end_ms);
    need(nil(d.rejection_ms) === nil(d.rejection_offset) && nil(d.rejection_ms) === nil(d.rejection_size));
    if (nil(d.rejection_ms)) {
      need(["empty","prefix","ambiguous"].includes(d.framer) && d.phase === "none" && d.category === "none" && d.message === "unclassified");
    } else {
      need(!nil(d.first_rx_ms) && d.first_rx_ms <= d.rejection_ms && d.rejection_ms <= d.last_rx_ms);
      need(d.framer === "refused" && d.category === "protocol" && d.phase !== "none" && messages.get(d.phase).includes(d.message));
      need(d.start_offset <= d.rejection_offset && d.rejection_offset < d.end_offset);
      need(d.rejection_size > 0 && d.rejection_size <= d.end_offset-d.rejection_offset);
    }
    if (!nil(d.eof_ms)) {
      need(150000 <= d.eof_ms && d.eof_ms <= d.end_ms && r.peer_eofs > 0);
      if (transportEof && r.peer_eofs === 1) need(d.eof_ms === eof);
    }
    if (transportEof && eof >= 150000 && eof <= d.end_ms) need(d.eof_ms === eof);
    if (["frame_boundary","message_classification","request_correlation","response_validation"].includes(phase) && causal >= 150000 && causal <= d.end_ms)
      need(d.rejection_ms === causal && d.phase === phase && d.category === category && d.message === message);
  }
  if (!nil(s.first_read_ok_ms)) {
    const lastReadMin=s.first_read_ok_ms+(r.recovery_reads_ok-1)*60000;
    need(lastReadMin <= (nil(s.end_ms) ? end : s.end_ms));
    if (d.observed && lastReadMin >= 150000 && lastReadMin <= d.end_ms)
      need(d.bytes > 0 && d.last_rx_ms >= lastReadMin);
    if (d.observed && s.first_read_ok_ms >= 150000 && s.first_read_ok_ms <= d.end_ms)
      need(d.bytes > 0 && d.first_rx_ms <= s.first_read_ok_ms);
  }
  return JSON.parse(JSON.stringify(Object.fromEntries(expected.sort().map(k => [k,r[k]]))));
}
module.exports = {validateV3};
