//! l1_server -- the verified L1 store (`si_concurrent::SiConcurrent`, Verus-verified:
//! every state installed behind its reader-writer lock satisfies `SiStore::inv`,
//! whose last conjunct is `!a1_struct(trace)`) exposed over JSON lines on stdio so
//! that the live LangGraph study (probes/303_live_a1_outcome.py --modes verified)
//! takes its commit/abort decision from the verified bytes instead of from an
//! application-layer re-read.
//!
//!   cargo build --release --example l1_server
//!   target/release/examples/l1_server            # one JSON object per line, in and out
//!
//! Protocol (cells, values and agents are small integers; the harness interns strings):
//!   {"op":"begin","agent":1,"cells":[3]}        -> {"snap":7,"read_time":12,"read_values":[[3,5]]}
//!   {"op":"commit","snap":7,"writes":[[4,9]]}   -> {"ok":true,"time":13}      (ok=false: refused, clock unchanged)
//!   {"op":"clock"}                              -> {"time":13}
//!   {"op":"trace"}                              -> {"trace":[{"agent":1,"read_cells":[3],"read_time":12,"write_cells":[4],"write_time":13},...]}
//!   {"op":"quit"}                               -> (exit 0)
//!
//! What is trusted here, on top of the crate's trust base: this ~100-line bridge
//! (serde_json parsing, the snapshot table) and the harness's interning. The
//! validation decision itself -- `validate` / `commit_step` -- is the verified code.
use agent_consistency_runtime::si_concurrent::{Cell, SiConcurrent, Snapshot, Val};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{self, BufRead, Write};

fn u(v: &Value) -> Option<u64> {
    v.as_u64()
}

fn main() {
    let store = SiConcurrent::new();
    let mut snaps: HashMap<u64, Snapshot> = HashMap::new();
    let mut next_snap: u64 = 1;
    let stdin = io::stdin();
    let mut out = io::stdout();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        if line.trim().is_empty() {
            continue;
        }
        let req: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                let _ = writeln!(out, "{}", json!({"error": format!("bad json: {e}")}));
                let _ = out.flush();
                continue;
            }
        };
        let reply = match req.get("op").and_then(|o| o.as_str()).unwrap_or("") {
            "begin" => {
                let agent = req.get("agent").and_then(u).unwrap_or(0) as usize;
                let cells: Vec<Cell> = req
                    .get("cells")
                    .and_then(|c| c.as_array())
                    .map(|a| a.iter().filter_map(u).map(|x| x as usize).collect())
                    .unwrap_or_default();
                let snap = store.begin(agent, cells);
                let id = next_snap;
                next_snap += 1;
                let rv: Vec<Value> = snap.read_values.iter().map(|(c, v)| json!([c, v])).collect();
                let reply = json!({"snap": id, "read_time": snap.read_time, "read_values": rv});
                snaps.insert(id, snap);
                reply
            }
            "commit" => {
                let id = req.get("snap").and_then(u).unwrap_or(0);
                let writes: Vec<(Cell, Val)> = req
                    .get("writes")
                    .and_then(|w| w.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|p| {
                                let p = p.as_array()?;
                                Some((u(p.get(0)?)? as usize, u(p.get(1)?)? as usize))
                            })
                            .collect()
                    })
                    .unwrap_or_default();
                match snaps.remove(&id) {
                    Some(snap) => {
                        let (ok, t) = store.commit(snap, &writes);
                        json!({"ok": ok, "time": t})
                    }
                    None => json!({"error": "unknown snapshot"}),
                }
            }
            "clock" => json!({"time": store.clock()}),
            "trace" => {
                // read the trace under a shared handle; records are plain data
                let handle = store.lock.acquire_read();
                let s = handle.borrow();
                let recs: Vec<Value> = s
                    .trace
                    .iter()
                    .map(|r| {
                        json!({"agent": r.agent, "read_cells": r.read_cells, "read_time": r.read_time,
                               "write_cells": r.write_cells, "write_time": r.write_time})
                    })
                    .collect();
                handle.release_read();
                json!({"trace": recs})
            }
            "quit" => {
                let _ = writeln!(out, "{}", json!({"bye": true}));
                let _ = out.flush();
                return;
            }
            other => json!({"error": format!("unknown op {other}")}),
        };
        let _ = writeln!(out, "{}", reply);
        let _ = out.flush();
    }
}
