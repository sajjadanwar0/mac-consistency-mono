//! l3_server -- the VERIFIED L3 commit-order sequencer (`l3_exec::L3Sequencer`,
//! byte-identical to crates/verus-detector/src/lib_l3_exec.rs, 7 obligations:
//! its data-structure invariant pins the emitted order to the identity prefix
//! over completed calls, and `a6_free` is proved of every reachable state)
//! exposed over JSON lines on stdio, so that the ToolNode replay
//! (probes/301_a6_toolnode_real_latency.py --l3-server) externalizes real
//! effects in the order the verified bytes decide, under concurrent dispatch,
//! instead of through a Python twin or a sequential loop.
//!
//!   cargo build --release --example l3_server
//!   target/release/examples/l3_server          # one JSON object per line, in and out
//!
//! Protocol (calls are issuance indices 0..n):
//!   {"op":"new","n":5}            -> {"ok":true}
//!   {"op":"complete","i":3}       -> {"released":[...]}   the issuance indices the verified
//!                                                         sequencer externalized BY this
//!                                                         completion, in emission order (the
//!                                                         caller performs each released effect
//!                                                         now, in that order)
//!   {"op":"emitted"}              -> {"emitted":[0,1,...]} the full emitted order so far
//!   {"op":"quit"}                 -> (exit 0)
//!
//! `complete(i)` has the verified precondition `i < n`; this bridge checks it
//! and refuses with an error instead of calling the erased-precondition code.
//! What is trusted on top of the crate's trust base: this ~70-line bridge and
//! the harness's mapping of tool names to issuance indices.
use agent_consistency_runtime::l3_exec::L3Sequencer;
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

fn main() {
    let mut seq: Option<L3Sequencer> = None;
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
            "new" => {
                let n = req.get("n").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                seq = Some(L3Sequencer::new(n));
                json!({"ok": true, "n": n})
            }
            "complete" => match seq.as_mut() {
                None => json!({"error": "no sequencer: send {\"op\":\"new\",\"n\":N} first"}),
                Some(s) => {
                    let i = req.get("i").and_then(|v| v.as_u64()).unwrap_or(u64::MAX) as usize;
                    if i >= s.n {
                        json!({"error": format!("i={i} out of range (n={})", s.n)})
                    } else {
                        let before = s.externalized.len();
                        s.complete(i);
                        let released: Vec<usize> = s.externalized[before..].to_vec();
                        json!({"released": released})
                    }
                }
            },
            "emitted" => match seq.as_ref() {
                None => json!({"emitted": []}),
                Some(s) => json!({"emitted": s.externalized.clone()}),
            },
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
