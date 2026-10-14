//! detect_a1_verified -- Definition 1 decided by the VERIFIED exec detector.
//!
//! `detect_a1_exec::detect_a1` is byte-identical to
//! `crates/verus-detector/src/lib_detect_a1_exec.rs` (9 obligations under the
//! pinned Verus build; `harness/macaudit/verified_bytes_gate.sh` fails if the
//! two files differ).  It is proved sound and complete against
//! `is_a1_witness` over `OpRec`s whose cells and values are `usize`.  This
//! file is the ONLY code between those verified bytes and the string-valued
//! `OpRecord`s the instrumentation emits, and it is listed in the paper's
//! trust base as such.  It does three things, each stated so a reader can
//! check that none of them can manufacture or hide a witness:
//!
//! 1. Interning.  Every distinct cell name gets a distinct `usize`, every
//!    distinct value string gets a distinct `usize` (first occurrence wins; a
//!    `HashMap` makes the map injective by construction), so
//!    `rv != wv` on strings holds iff it holds on the interned integers.
//! 2. Well-formedness.  The verified detector's precondition `wf_hist` asks
//!    that no record lists one cell twice in its read or write vector.  A
//!    declared cell is kept at its first position and later duplicates are
//!    dropped; `read_values`/`write_values` are maps, so a duplicate can only
//!    repeat the same (cell, value) pair.
//! 3. Absent values.  The verified predicate ranges over (cell, value) pairs,
//!    so a read cell whose value the record does not carry is encoded with the
//!    sentinel `ABSENT`, a value no JSON record can contain (it holds a NUL
//!    byte).  A write of any recorded value to that cell inside the window
//!    then fires -- the behaviour of the hand-written scorer this function
//!    replaces (it compared `Option`s), and a case `hypothesis_gates.py`
//!    reports as absent from every committed record (no read cell without a
//!    value in 36,036 records).
//!
//! The verified predicate carries no agent conjunct.  Lemma 1 of the paper
//! shows the conjunct is implied under per-agent non-overlap, which the same
//! gate checks on every record (0 violations); on a history that violates
//! non-overlap this detector over-reports relative to Definition 1, the safe
//! direction for a detector, and `same_agent_pairs` lets a caller count how
//! often that happened.
use crate::detect_a1_exec::{detect_a1, OpRec};
use crate::oprecord::OpRecord;
use std::collections::HashMap;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct A1WitnessIdx {
    pub i: usize,
    pub j: usize,
    pub cell: String,
}

/// A value string no serde_json-decoded record can equal: it contains a NUL
/// byte, and the recorders emit values through `json.dumps` of plain text.
pub const ABSENT: &str = "\u{0}ABSENT\u{0}";

#[derive(Default)]
struct Intern {
    map: HashMap<String, usize>,
    names: Vec<String>,
}

impl Intern {
    fn id(&mut self, s: &str) -> usize {
        if let Some(&k) = self.map.get(s) {
            return k;
        }
        let k = self.names.len();
        self.names.push(s.to_string());
        self.map.insert(s.to_string(), k);
        k
    }
}

/// Intern a string-valued history into the verified detector's representation.
/// Returns the records and the cell-name table (index = interned id).
pub fn encode(h: &[OpRecord]) -> (Vec<OpRec>, Vec<String>) {
    let mut cells = Intern::default();
    let mut vals = Intern::default();
    let mut out = Vec::with_capacity(h.len());
    for r in h {
        let mut read: Vec<(usize, usize)> = Vec::new();
        for c in &r.read_set {
            let cid = cells.id(c);
            if read.iter().any(|(k, _)| *k == cid) {
                continue; // wf_keys: first occurrence wins
            }
            let v = r.read_values.get(c).map(|s| s.as_str()).unwrap_or(ABSENT);
            read.push((cid, vals.id(v)));
        }
        let mut write: Vec<(usize, usize)> = Vec::new();
        for c in &r.write_set {
            let cid = cells.id(c);
            if write.iter().any(|(k, _)| *k == cid) {
                continue;
            }
            let v = r.write_values.get(c).map(|s| s.as_str()).unwrap_or(ABSENT);
            write.push((cid, vals.id(v)));
        }
        out.push(OpRec {
            read,
            read_time: r.read_time,
            write,
            write_time: r.write_time,
        });
    }
    (out, cells.names)
}

/// Definition 1 (modulo the agent conjunct, see the module comment) decided by
/// the verified bytes.  `None` means: no witness in the whole history, by the
/// detector's verified completeness.
pub fn detect_a1_verified(h: &[OpRecord]) -> Option<A1WitnessIdx> {
    let (recs, names) = encode(h);
    detect_a1(&recs).map(|(i, j, c)| A1WitnessIdx {
        i,
        j,
        cell: names[c].clone(),
    })
}

/// Witnesses of the verified predicate whose two records belong to the SAME
/// agent: the pairs on which the verified predicate is stronger than
/// Definition 1.  Zero on every history satisfying per-agent non-overlap
/// (Lemma 1); reported so a trace that violates the hypothesis is visible.
pub fn same_agent_pairs(h: &[OpRecord]) -> usize {
    let mut n = 0;
    for i in 0..h.len() {
        for j in 0..h.len() {
            if i == j || h[i].agent != h[j].agent {
                continue;
            }
            for c in &h[i].read_set {
                if !h[j].writes_cell(c) {
                    continue;
                }
                if !(h[i].read_time < h[j].write_time && h[j].write_time < h[i].write_time) {
                    continue;
                }
                let rv = h[i].read_values.get(c).map(|s| s.as_str()).unwrap_or(ABSENT);
                let wv = h[j].write_values.get(c).map(|s| s.as_str()).unwrap_or(ABSENT);
                if rv != wv {
                    n += 1;
                }
            }
        }
    }
    n
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    fn op(agent: &str, rs: &[(&str, &str)], rt: u64, ws: &[(&str, &str)], wt: u64) -> OpRecord {
        OpRecord {
            agent: agent.into(),
            read_set: rs.iter().map(|(c, _)| c.to_string()).collect(),
            read_values: rs.iter().map(|(c, v)| (c.to_string(), v.to_string())).collect::<BTreeMap<_, _>>(),
            read_time: rt,
            write_set: ws.iter().map(|(c, _)| c.to_string()).collect(),
            write_values: ws.iter().map(|(c, v)| (c.to_string(), v.to_string())).collect::<BTreeMap<_, _>>(),
            write_time: wt,
            planned_tool: None,
            tools_used: vec![],
            tools_visible_at_read: vec![],
            io: vec![],
            co: vec![],
        }
    }

    #[test]
    fn canonical_witness_fires() {
        // the TLC witness of Sec. 3.1: a2 reads c1=NULL at 0, a1 commits c1=v1 at 1, a2 commits at 2
        let h = vec![
            op("a1", &[], 0, &[("c1", "v1")], 1),
            op("a2", &[("c1", "NULL")], 0, &[("c2", "x")], 2),
        ];
        let w = detect_a1_verified(&h).expect("witness");
        assert_eq!((w.i, w.j, w.cell.as_str()), (1, 0, "c1"));
    }

    #[test]
    fn same_value_write_does_not_fire() {
        let h = vec![
            op("a1", &[], 0, &[("c1", "NULL")], 1),
            op("a2", &[("c1", "NULL")], 0, &[("c2", "x")], 2),
        ];
        assert!(detect_a1_verified(&h).is_none());
    }

    #[test]
    fn write_after_commit_does_not_fire() {
        let h = vec![
            op("a2", &[("c1", "NULL")], 0, &[("c2", "x")], 1),
            op("a1", &[], 0, &[("c1", "v1")], 2),
        ];
        assert!(detect_a1_verified(&h).is_none());
    }

    #[test]
    fn absent_read_value_fires_like_the_port_did() {
        let mut r = op("a2", &[], 0, &[("c2", "x")], 2);
        r.read_set.push("c1".into()); // declared, no value
        let h = vec![op("a1", &[], 0, &[("c1", "v1")], 1), r];
        assert!(detect_a1_verified(&h).is_some());
    }

    #[test]
    fn duplicate_declared_cells_are_well_formed() {
        let mut r = op("a2", &[("c1", "NULL")], 0, &[("c2", "x")], 2);
        r.read_set.push("c1".into());
        let (recs, _) = encode(&[r]);
        assert_eq!(recs[0].read.len(), 1);
    }
}
