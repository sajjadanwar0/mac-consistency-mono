//! l5_server -- the VERIFIED L5 basis ledger (`l5_exec::L5Ledger`, byte-identical
//! to crates/verus-detector/src/lib_l5_exec.rs: `mark` is total -- after it, no
//! effect whose basis the write superseded is without an obligation -- `report`
//! records the compensator's verdict exactly, `open_flags` is the obligation
//! bits) exposed over JSON lines on stdio, so that the ledger arm of the world
//! study (probes/304_ledger_world.py --ledger exec) keeps its obligations in
//! these bytes instead of in a Python dictionary.
//!
//!   cargo build --release --example l5_server
//!   target/release/examples/l5_server          # one JSON object per line, in and out
//!
//! Protocol (cells and values are small integers: the bridge's caller interns
//! the probe's strings, as the A1 scorer's interning wrapper does):
//!   {"op":"new"}                                   -> {"ok":true}
//!   {"op":"register","cell":c,"basis":b}           -> {"id":n}          an effect is out on basis (c, b)
//!   {"op":"mark","cell":c,"value":v}               -> {"fresh":[...],"retried":[...]}
//!        the indices obliged by this write and those already open (a retry); the
//!        caller holds the store lock across this call, so the registration is
//!        atomic with the write it reports
//!   {"op":"report","id":i,"value":v,"ok":true|false} -> {"obligation":bool,"basis":v',"attempts":k}
//!        the compensator's verdict on obligation i after the supersession to v
//!   {"op":"open"}                                  -> {"open":[...],"n":len}   the obligation bits, as indices
//!   {"op":"quit"}                                  -> (exit 0)
//!
//! `report` has the verified preconditions `i < len` and `attempts < usize::MAX`;
//! this bridge checks both and refuses with an error instead of calling the
//! erased-precondition code.  What is trusted on top of the crate's trust base:
//! this bridge, the caller's interning, the caller's store hook (which decides
//! WHEN mark is called and holds the lock), and the compensator.
use agent_consistency_runtime::l5_exec::L5Ledger;
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

fn main() {
    let mut ledger: Option<L5Ledger> = None;
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
        let get = |k: &str| req.get(k).and_then(|v| v.as_u64());
        let reply = match req.get("op").and_then(|o| o.as_str()).unwrap_or("") {
            "new" => {
                ledger = Some(L5Ledger::new());
                json!({"ok": true})
            }
            "register" => match ledger.as_mut() {
                None => json!({"error": "no ledger: send {\"op\":\"new\"} first"}),
                Some(l) => match (get("cell"), get("basis")) {
                    (Some(c), Some(b)) => {
                        let id = l.register_effect(c as usize, b as usize);
                        json!({"id": id})
                    }
                    _ => json!({"error": "register needs integer cell and basis"}),
                },
            },
            "mark" => match ledger.as_mut() {
                None => json!({"error": "no ledger"}),
                Some(l) => match (get("cell"), get("value")) {
                    (Some(c), Some(v)) => {
                        let (fresh, retried) = l.mark(c as usize, v as usize);
                        json!({"fresh": fresh, "retried": retried})
                    }
                    _ => json!({"error": "mark needs integer cell and value"}),
                },
            },
            "report" => match ledger.as_mut() {
                None => json!({"error": "no ledger"}),
                Some(l) => {
                    let ok = req.get("ok").and_then(|v| v.as_bool());
                    match (get("id"), get("value"), ok) {
                        (Some(i), Some(v), Some(ok)) => {
                            let i = i as usize;
                            if i >= l.len() {
                                json!({"error": format!("report: id {i} out of range (len {})", l.len())})
                            } else if l.effects[i].attempts == usize::MAX {
                                json!({"error": "report: attempts counter saturated"})
                            } else {
                                l.report(i, v as usize, ok);
                                let e = &l.effects[i];
                                json!({"obligation": e.obligation, "basis": e.basis, "attempts": e.attempts})
                            }
                        }
                        _ => json!({"error": "report needs integer id and value and boolean ok"}),
                    }
                }
            },
            "open" => match ledger.as_ref() {
                None => json!({"error": "no ledger"}),
                Some(l) => {
                    let flags = l.open_flags();
                    let open: Vec<usize> = flags.iter().enumerate().filter(|(_, f)| **f).map(|(i, _)| i).collect();
                    json!({"open": open, "n": l.len()})
                }
            },
            "quit" => {
                let _ = writeln!(out, "{}", json!({"bye": true}));
                let _ = out.flush();
                return;
            }
            other => json!({"error": format!("unknown op {other:?}")}),
        };
        let _ = writeln!(out, "{}", reply);
        let _ = out.flush();
    }
}
