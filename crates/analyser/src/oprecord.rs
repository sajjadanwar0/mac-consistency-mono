use serde::{Deserialize, Serialize};
use std::collections::HashMap;

pub type CellId = String;
pub type Value = String;
pub type AgentId = String;
pub type ToolId = String;
pub type Time = u64;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OpRecord {
    /// `agent` is the canonical key (instrument.py, the runtime emitter);
    /// `agent_id` is accepted for the cookbook (production_extractor.py) and
    /// MAST (mast_adapter.py) op-records.  The two keys are reconciled in
    /// `load_history` (see `normalize_agent_key`), NOT by a serde alias: the
    /// probe-303 records carry BOTH keys with the same value, and a serde
    /// alias rejects that line as "duplicate field `agent`" (verified_scorer_gate,
    /// 2026-10-14, every probe-303 cell).
    pub agent: AgentId,
    pub read_set: Vec<CellId>,
    pub read_values: HashMap<CellId, Value>,
    pub read_time: Time,
    pub write_set: Vec<CellId>,
    pub write_values: HashMap<CellId, Value>,
    pub write_time: Time,
    #[serde(default)]
    pub planned_tool: Option<ToolId>,
    #[serde(default)]
    pub tools_used: Vec<ToolId>,
    #[serde(default)]
    pub tools_visible_at_read: Vec<ToolId>,
    #[serde(default)]
    pub io: Vec<(CellId, Value)>,
    #[serde(default)]
    pub co: Vec<(CellId, Value)>,
}

impl OpRecord {
    #[allow(dead_code)]
    pub fn reads(&self, c: &str) -> bool {
        self.read_set.iter().any(|x| x == c)
    }
    pub fn writes(&self, c: &str) -> bool {
        self.write_set.iter().any(|x| x == c)
    }
}

/// Reconcile the two spellings of the agent key on one JSON object:
/// `agent` (canonical) and `agent_id` (cookbook / MAST / probe 303, which
/// writes both).  Exactly one value must result; two different values are an
/// error, since a scorer must not guess which agent issued the operation.
fn normalize_agent_key(v: &mut serde_json::Value) -> Result<(), String> {
    let obj = match v.as_object_mut() {
        Some(o) => o,
        None => return Err("op-record is not a JSON object".into()),
    };
    let alias = obj.remove("agent_id");
    match (obj.get("agent"), alias) {
        (Some(a), Some(b)) if *a != b => Err(format!(
            "agent {} and agent_id {} disagree on one record",
            a, b
        )),
        (Some(_), _) => Ok(()),
        (None, Some(b)) => {
            obj.insert("agent".to_string(), b);
            Ok(())
        }
        (None, None) => Err("missing field `agent` (or `agent_id`)".into()),
    }
}

/// Parse one op-record line.  Public so that the unit tests and any other
/// front end read records exactly as the scorer does.
pub fn parse_record(line: &str) -> Result<OpRecord, String> {
    let mut v: serde_json::Value = serde_json::from_str(line).map_err(|e| e.to_string())?;
    normalize_agent_key(&mut v)?;
    serde_json::from_value(v).map_err(|e| e.to_string())
}

pub fn load_history(path: &std::path::Path) -> std::io::Result<Vec<OpRecord>> {
    use std::io::BufRead;
    let f = std::fs::File::open(path)?;
    let r = std::io::BufReader::new(f);
    let mut history = Vec::new();
    for (lineno, line) in r.lines().enumerate() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let op = parse_record(&line).map_err(|e| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("line {}: {}", lineno + 1, e),
            )
        })?;
        history.push(op);
    }
    Ok(history)
}

#[cfg(test)]
mod tests {
    use super::*;

    const BASE: &str = r#""read_set": [], "read_values": {}, "read_time": 0, "write_set": ["c"], "write_values": {"c": "v"}, "write_time": 1"#;

    #[test]
    fn canonical_key_only() {
        let r = parse_record(&format!(r#"{{"agent": "flight", {}}}"#, BASE)).unwrap();
        assert_eq!(r.agent, "flight");
    }

    #[test]
    fn alias_key_only() {
        let r = parse_record(&format!(r#"{{"agent_id": "flight", {}}}"#, BASE)).unwrap();
        assert_eq!(r.agent, "flight");
    }

    #[test]
    fn both_keys_same_value_is_accepted() {
        // the probe-303 shape that the serde alias rejected as a duplicate field
        let r = parse_record(&format!(
            r#"{{"agent": "seed", "agent_id": "seed", "mode": "vanilla", {}}}"#,
            BASE
        ))
        .unwrap();
        assert_eq!(r.agent, "seed");
    }

    #[test]
    fn both_keys_different_values_is_an_error() {
        let e = parse_record(&format!(r#"{{"agent": "a", "agent_id": "b", {}}}"#, BASE)).unwrap_err();
        assert!(e.contains("disagree"), "{}", e);
    }

    #[test]
    fn neither_key_is_an_error() {
        let e = parse_record(&format!(r#"{{{}}}"#, BASE)).unwrap_err();
        assert!(e.contains("missing field `agent`"), "{}", e);
    }
}
