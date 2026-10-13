# mac-consistency monorepo. Conventions (as in resume-contract): ASCII-only
# artifacts; complete files (git holds history, not filename suffixes);
# numbered probes continue from the highest committed number (next: 301);
# every audit gates on committed receipts under results/ and on CLAIMS.json.
UV ?= uv
TLA_TOOLS ?= $(CURDIR)/tools/tla2tools.jar

.PHONY: setup tlc lattice32 tlaps verus rust data census audit claims clean

setup:            ## resolve+install the root harness env and every matrix cell under envs/
	$(UV) sync
	for e in envs/*/; do [ -f $$e/pyproject.toml ] && $(UV) sync --project $$e || true; done

tlc:              ## [1] TLC: witnesses, vacuity, the 15 CommitOrder verdicts, lattice16 (64 + 16 runs), lattice32 (160 runs, A7/G7)
	QUICK=0 ./reproduce.sh --formal-only

lattice32:        ## [1b] only the 32-point matrix over Guarded5.tla (~1-2 h); --only NoA7 for the two A7 cells
	cd formal/tla && ./lattice32.sh $(TLA_TOOLS)

tlaps:            ## [2] TLAPS: Hierarchy 15 / A1LowerBound 28 / CommitOrder 60 obligations
	cd formal/tla && tlapm --toolbox 0 0 matrix/Hierarchy.tla && tlapm --toolbox 0 0 A1LowerBound.tla && tlapm --toolbox 0 0 CommitOrder.tla

verus:            ## [3] Verus: pinned build, per-file counts -> results/verus/count.json
	cd crates/verus-detector && bash ../../harness/macaudit/verus_count.sh --full

rust:             ## [5] cargo test; L2/L4 measurement receipts
	cargo test --workspace --release

data:             ## [4] offline rescoring gates (python3 only)
	./reproduce.sh --data-only

census:           ## [6] census offline checks
	PYTHONPATH=probes/_modules python3 probes/*_langgraph_census.py --check --dir archaeology/langgraph_census
	PYTHONPATH=probes/_modules python3 probes/*_langgraph_static.py --selftest

claims:           ## regenerate CLAIMS.json skeleton (edit by hand; verus_count.sh --json overwrites 'verus')
	python3 harness/macaudit/claims_gate.py --init --claims CLAIMS.json

audit:            ## single-command audit: every headline figure re-derived from committed data
	./reproduce.sh --strict

clean:
	rm -rf target tools/tlc_* tools/*.log formal/tla/lattice16_runs formal/tla/lattice32_runs formal/tla/states envs/*/.venv .venv
