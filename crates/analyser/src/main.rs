//! analyser -- scores one op-record trace (JSON lines) for the four anomalies.
//!
//! Since this version the A1 verdict is taken by the VERIFIED detector
//! (`agent_consistency_runtime::detect_a1_verified`, which applies the exec
//! detector byte-identical to the Verus-verified `lib_detect_a1_exec.rs`), not
//! by the hand-written port in `anomalies.rs`.  The port is kept and scored
//! beside it; `--strict` exits non-zero if the two disagree on a trace, and
//! `harness/macaudit/verified_scorer_gate.py` runs this binary over every
//! published cell and records the agreement as a receipt.
//!
//!   analyser <trace.jsonl>              human-readable summary
//!   analyser --json <trace.jsonl>       one JSON object (for the gates)
//!   analyser --strict <trace.jsonl>     exit 3 if the verified detector and the port disagree
mod anomalies;
mod classifier;
mod oprecord;

use agent_consistency_runtime::detect_a1_verified::{detect_a1_verified, same_agent_pairs};
use agent_consistency_runtime::oprecord::OpRecord as RtRecord;
use std::path::PathBuf;

fn to_runtime(h: &[oprecord::OpRecord]) -> Vec<RtRecord> {
    h.iter()
        .map(|r| RtRecord {
            agent: r.agent.clone(),
            read_set: r.read_set.clone(),
            read_values: r.read_values.iter().map(|(k, v)| (k.clone(), v.clone())).collect(),
            read_time: r.read_time,
            write_set: r.write_set.clone(),
            write_values: r.write_values.iter().map(|(k, v)| (k.clone(), v.clone())).collect(),
            write_time: r.write_time,
            planned_tool: r.planned_tool.clone(),
            tools_used: r.tools_used.clone(),
            tools_visible_at_read: r.tools_visible_at_read.clone(),
            io: r.io.clone(),
            co: r.co.clone(),
        })
        .collect()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let json_out = args.iter().any(|a| a == "--json");
    let strict = args.iter().any(|a| a == "--strict");
    let path = match args.iter().skip(1).find(|a| !a.starts_with("--")) {
        Some(p) => PathBuf::from(p),
        None => {
            eprintln!("usage: analyser [--json] [--strict] <trace.jsonl>");
            std::process::exit(1);
        }
    };
    let history = match oprecord::load_history(&path) {
        Ok(h) => h,
        Err(e) => {
            eprintln!("error reading {}: {}", path.display(), e);
            std::process::exit(2);
        }
    };

    let rt = to_runtime(&history);
    let a1_verified = detect_a1_verified(&rt);          // the verified bytes decide
    let a1_port = anomalies::detect_a1(&history);        // the former scorer, kept as a cross-check
    let same_agent = same_agent_pairs(&rt);
    let a2 = anomalies::detect_a2(&history);
    let a3 = anomalies::detect_a3(&history);
    let a6 = anomalies::detect_a6(&history);
    let agree = a1_verified.is_some() == !a1_port.is_empty();
    let level = classifier::classify(&history, a1_verified.is_some());

    if json_out {
        println!(
            "{}",
            serde_json::json!({
                "file": path.display().to_string(),
                "operations": history.len(),
                "a1_verified": a1_verified.is_some(),
                "a1_witness": a1_verified.as_ref().map(|w| serde_json::json!({"i": w.i, "j": w.j, "cell": w.cell})),
                "a1_port": !a1_port.is_empty(),
                "a1_port_count": a1_port.len(),
                "a1_same_agent_pairs": same_agent,
                "a1_agree": agree,
                "a2": a2.len(), "a3": a3.len(), "a6": a6.len(),
                "level": level.label(),
            })
        );
    } else {
        println!("=== Trace summary ===");
        println!("file: {}", path.display());
        println!("operations: {}", history.len());
        println!();
        println!("=== Anomaly detection ===");
        println!(
            "A1 (Stale-Generation), verified detector: {}   [port: {} occurrence(s); agree: {}]",
            if a1_verified.is_some() { "WITNESS" } else { "none" },
            a1_port.len(),
            agree
        );
        if same_agent > 0 {
            println!("  note: {} same-agent window pair(s) -- per-agent non-overlap violated on this trace; the verified predicate over-reports there", same_agent);
        }
        println!("A2 (Phantom-Tool):           {} occurrence(s)", a2.len());
        println!("A3 (Causal-Cascade):         {} occurrence(s)", a3.len());
        println!("A6 (Tool-Effect-Reorder):    {} occurrence(s)", a6.len());
        if let Some(w) = &a1_verified {
            println!();
            println!("--- A1 witness (verified detector) ---");
            println!(
                "  i={} j={} cell={}: agent {} read {} at t={}, agent {} wrote {} at t={}, agent {} committed at t={}",
                w.i,
                w.j,
                w.cell,
                history[w.i].agent,
                history[w.i].read_values.get(&w.cell).map(|s| s.as_str()).unwrap_or("?"),
                history[w.i].read_time,
                history[w.j].agent,
                history[w.j].write_values.get(&w.cell).map(|s| s.as_str()).unwrap_or("?"),
                history[w.j].write_time,
                history[w.i].agent,
                history[w.i].write_time,
            );
        }
        println!();
        println!("=== Level classification ===");
        println!("Highest level satisfied: {}", level.label());
        println!();
    }
    if strict && !agree {
        eprintln!("DISAGREEMENT: verified detector {} vs port {} on {}", a1_verified.is_some(), !a1_port.is_empty(), path.display());
        std::process::exit(3);
    }
}
