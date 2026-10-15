#!/usr/bin/env python3
r"""claims_gate.py -- ONE source of truth for every headline number.

The artifact currently states FIVE different Verus obligation totals:
  pilot README        274 curated / 295 full
  pilot REPRODUCE.md  331 curated / 352 full
  tla README          338 curated / 359 full
  runtime README      358 curated / (379 full)
  paper (v3)          364 curated / 385 full
  paper (v4)          371 curated / 392 full   (pinned build; + lib_l5_ledger.rs)
and per-file counts that disagree with the paper (lib_l2_safety 22 vs 33,
lib_l4_safety 5 vs 9, lib_l2_exec 49 vs 73, lib_l4_exec 9 vs 11).  A referee who
opens any README finds a number that contradicts the paper.

This gate reads CLAIMS.json (the single source of truth, which `verus_count.sh
--json` and the measurement examples should WRITE) and greps every prose file
for obligation-count-shaped phrases, failing on any figure that is not the
claimed one.  Run it in CI and before every submission.

    python3 claims_gate.py --claims CLAIMS.json --scan README.md docs paper/*.tex
    python3 claims_gate.py --init          # write a CLAIMS.json skeleton from the paper's figures

Added 2026-10-14 (a referee opens the artifact URL the paper prints, not the working tree):
    --artifact-url paper/main.tex    the \url{} in the title footnote must name the mono repo AND a
                                     release tag or commit (CLAIMS.json "artifact": {"url", "tag"});
    --remote-readme                  fetch the README the artifact URL serves (raw.githubusercontent.com)
                                     and scan it with the same patterns, so a stale public README fails
                                     the gate before a reviewer finds it.
"""
from __future__ import annotations
import argparse, json, os, re, sys

SKELETON = {
    "verus": {
        "curated_total": 371, "full_total": 392, "errors": 0,   # pinned build 0.2026.09.13, incl. lib_l5_ledger.rs (7)
        "pin": "0.2026.09.13.671956e",
        "per_file": {
            "lib_a3_residue.rs": 6, "lib_a4_split_view.rs": 9, "lib_concurrent_semantics.rs": 9,
            "lib_consistency_lattice.rs": 53, "lib_default_si.rs": 9, "lib_detect_a1_exec.rs": 9,
            "lib_detector_equivalence.rs": 24, "lib_l2_exec.rs": 73, "lib_l2_projection.rs": 3,
            "lib_l2_safety.rs": 33, "lib_l3_exec.rs": 7, "lib_l3_safety.rs": 6, "lib_l3_sequencer.rs": 5,
            "lib_l4_exec.rs": 11, "lib_l4_safety.rs": 9, "lib_l5_ledger.rs": 7, "lib_langgraph_refinement.rs": 7,
            "lib_occ_l2_refinement.rs": 8, "lib_pessimistic_exec.rs": 5, "lib_pessimistic_invariant.rs": 3,
            "lib_refinement_default_si.rs": 18, "lib_refinement_pessimistic.rs": 31,
            "lib_refinement_ssi_chain.rs": 19, "lib_refinement_ssi.rs": 18, "lib.rs": 23,
            "lib_rustbelt_interface.rs": 4, "lib_si_commit_invariant.rs": 4, "lib_pess_concurrent.rs": 31,
            "lib_si_concurrent.rs": 18, "lib_si_projection.rs": 3, "lib_ssi.rs": 8,
        },
    },
    "tlaps": {"Hierarchy.tla": 15, "A1LowerBound.tla": 28, "CommitOrder.tla": 60},
    "tlc": {"lattice16_runs": 64, "lattice16_mismatches": 0, "lattice16_maxops3_runs": 16,
            "commitorder_verdicts": 15, "commitorder_memory_states": 2961434},
    "live_a1": {"gpt-4o-mini": {"vanilla": 60, "validated": 0, "sequential": 0, "superstep_completion": 42},
                "claude-haiku-4-5": {"vanilla": 91, "validated": 0, "sequential": 0, "superstep_completion": 72},
                "llama3.2": {"vanilla": 1, "validated": 0, "sequential": 0, "superstep_completion": 26}},
    "l2_measure": {"def3_unguarded": [519, 624, 563], "def3_verified": [0, 0, 0],
                   "exposed_unguarded": [1538, 2059, 2010], "exposed_verified": [402, 547, 549],
                   "relabeled_cascade": [767, 1288, 1239]},
    "l4_measure": {"phantom_live": [630, 505, 387], "phantom_verified": [0, 0, 0]},
    "live_l2": {"retractions": {"claude-haiku-4-5": 1, "gpt-4o-mini": 3, "llama3.2": 62}, "a3_verified": 0},
    "census": {"repos_sampled": 180, "repos_with_graph": 98, "sites": 407, "parallel": 11, "confirmed": 0, "upper": 8},
    "toolnode_a6": {"gpt-4o-mini": {"batched": 30, "reordered": 22}, "llama3.2": {"batched": 3, "reordered": 2},
                    "claude-haiku-4-5": {"batched": 0, "reordered": 0}, "l3_reordered": 0},
}

# phrases that carry an obligation total in prose
PATTERNS = [
    (re.compile(r"(\d{3})\s*curated\s*/\s*(\d{3})\s*full"), ("verus", "curated_total", "full_total")),
    (re.compile(r"curated\s*=\s*(\d{3});\s*--full\s*=\s*(\d{3})"), ("verus", "curated_total", "full_total")),
    (re.compile(r"(\d{3})\s*(?:distinct\s+)?(?:verified\s+)?obligations"), ("verus", "curated_total", None)),
]
PER_FILE = re.compile(r"(lib[_a-z0-9]*\.rs)[^\n0-9]{0,40}?(\d{1,3})\b")


def scan(path: str, claims: dict) -> list[str]:
    problems = []
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return [f"{path}: unreadable"]
    if "SUPERSEDED (" in text[:400]:
        return []          # a bannered historical file: its figures are labeled as superseded
    v = claims["verus"]
    for pat, (sec, k1, k2) in PATTERNS:
        for m in pat.finditer(text):
            got = int(m.group(1))
            if got not in (v[k1], v.get("full_total")):
                problems.append(f"{path}: '{m.group(0).strip()}' -- claimed curated={v[k1]} full={v['full_total']}")
            if k2 and m.lastindex and m.lastindex >= 2 and int(m.group(2)) != v[k2]:
                problems.append(f"{path}: '{m.group(0).strip()}' -- claimed {k2}={v[k2]}")
    for m in PER_FILE.finditer(text):
        f, n = m.group(1), int(m.group(2))
        if f in v["per_file"] and n != v["per_file"][f] and n > 1:
            # tolerate line references like "lines 6-13"; only flag plausible counts
            ctx = text[max(0, m.start() - 30): m.end() + 30].replace("\n", " ")
            if re.search(r"verified|obligation|\|\s*\d", ctx):
                problems.append(f"{path}: {f} {n} -- claimed {v['per_file'][f]}  [{ctx.strip()}]")
    return problems


def artifact_url_check(tex_path: str, claims: dict) -> list[str]:
    """the paper's artifact footnote must point at the repository and revision CLAIMS.json names"""
    problems = []
    art = claims.get("artifact") or {}
    want_url, want_tag = art.get("url"), art.get("tag")
    if not want_url or not want_tag:
        return [f"CLAIMS.json has no artifact.url / artifact.tag (add them: the tag you pushed, e.g. v4.1-tse)"]
    try:
        tex = open(tex_path, encoding="utf-8").read()
    except OSError:
        return [f"{tex_path}: unreadable"]
    urls = re.findall(r"\\url\{([^}]*)\}", tex[: tex.find("\\section{") if "\\section{" in tex else len(tex)])
    if not any(want_url in u for u in urls):
        problems.append(f"{tex_path}: no \\url{{}} before the first section names the artifact {want_url} (found: {urls[:3]})")
    if want_tag not in tex:
        problems.append(f"{tex_path}: the release tag {want_tag} does not appear in the paper (the footnote must pin the revision)")
    return problems


def remote_readme(claims: dict) -> tuple[str | None, list[str]]:
    art = claims.get("artifact") or {}
    url, tag = art.get("url"), art.get("tag")
    if not url:
        return None, ["CLAIMS.json has no artifact.url"]
    m = re.search(r"github\.com/([^/]+)/([^/\s]+)", url)
    if not m:
        return None, [f"artifact.url {url} is not a github.com URL"]
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{tag or 'main'}/README.md"
    try:
        import urllib.request
        with urllib.request.urlopen(raw, timeout=20) as r:  # noqa: S310
            text = r.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return None, [f"could not fetch {raw}: {e} (push the tag first)"]
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".remote_README.md")
    open(tmp, "w", encoding="utf-8").write(text)
    return tmp, []


BLOCK_START = "% generated by harness/macaudit/claims_from_results.py -- do not edit; re-run the probes instead\n"
BLOCK_END = "% a regenerated claims_results.tex beside this file"


def inlined_block(tex_path: str) -> str | None:
    """the receipt-macro block that main.tex / supplement.tex carry inline (both files must be self-contained)"""
    s = open(tex_path, encoding="utf-8", errors="replace").read()
    if BLOCK_START not in s or BLOCK_END not in s:
        return None
    a = s.index(BLOCK_START); b = s.index(BLOCK_END)
    return s[a:b].rstrip("\n") + "\n"


def inlined_macros_check(tex_paths: list[str]) -> list[str]:
    """(1) every tex file carries the SAME inlined receipt block (the headline-number block is duplicated by design);
    (2) when paper/claims_results.tex exists beside them, the inlined block equals it (a regenerated receipt file that
    the inlined copy does not match means the PDFs were built from stale numbers)."""
    probs = []
    blocks = {p: inlined_block(p) for p in tex_paths if p.endswith(".tex") and os.path.exists(p)}
    blocks = {p: b for p, b in blocks.items() if b is not None}
    if len(blocks) >= 2:
        vals = list(blocks.values())
        if any(v != vals[0] for v in vals[1:]):
            probs.append("inlined receipt blocks differ between " + ", ".join(blocks))
    for p, b in blocks.items():
        cr = os.path.join(os.path.dirname(p) or ".", "claims_results.tex")
        if os.path.exists(cr):
            want = open(cr, encoding="utf-8", errors="replace").read().rstrip("\n") + "\n"
            if want != b:
                probs.append(f"{p}: inlined receipt block differs from {cr} (regenerate: paste claims_results.tex into the tex, or rebuild)")
    return probs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", default="CLAIMS.json")
    ap.add_argument("--scan", nargs="*", default=["README.md"])
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--artifact-url", default=None, help="paper/main.tex: check the artifact footnote against CLAIMS.json artifact.{url,tag}")
    ap.add_argument("--remote-readme", action="store_true", help="fetch and scan the README the artifact URL serves at artifact.tag")
    a = ap.parse_args()
    if a.init:
        with open(a.claims, "w") as f:
            json.dump(SKELETON, f, indent=1)
        print(f"wrote {a.claims} (skeleton from the paper's figures; let verus_count.sh --json overwrite 'verus')")
        return 0
    claims = json.load(open(a.claims))
    files = []
    for p in a.scan:
        if os.path.isdir(p):
            for root, _, fs in os.walk(p):
                files += [os.path.join(root, f) for f in fs if f.endswith((".md", ".tex", ".txt"))]
        elif os.path.exists(p):
            files.append(p)
    problems = []
    for f in sorted(set(files)):
        problems += scan(f, claims)
    if a.artifact_url:
        problems += artifact_url_check(a.artifact_url, claims)
    problems += inlined_macros_check([f for f in files if f.endswith(".tex")])
    if a.remote_readme:
        tmp, errs = remote_readme(claims)
        problems += errs
        if tmp:
            rp = scan(tmp, claims)
            problems += [x.replace(tmp, "REMOTE README") for x in rp]
            print(f"remote README at artifact.tag scanned: {len(rp)} mismatching figure(s)")
            os.remove(tmp)
    for p in problems:
        print("CLAIM-MISMATCH", p)
    print(f"{len(files)} file(s) scanned, {len(problems)} mismatching figure(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
