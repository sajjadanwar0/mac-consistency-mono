#!/usr/bin/env bash
# release_tag.sh -- freeze the revision the paper cites.  A referee opens the URL in the title
# footnote, not your working tree: the footnote must name THIS repository and a tag, every README
# must state the numbers CLAIMS.json states, and the gates must pass on the tagged tree.
#
#   ./scripts/release_tag.sh v4.1-tse            # run the gates, commit, tag, push the tag
#
# The tag name must equal CLAIMS.json "artifact.tag" (claims_gate.py --artifact-url checks the
# paper's footnote against it).  Re-tagging an existing name is refused: bump the tag instead.
set -euo pipefail
TAG="${1:?usage: release_tag.sh <tag>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
want="$(python3 -c 'import json;print(json.load(open("CLAIMS.json")).get("artifact",{}).get("tag",""))')"
[ "$want" = "$TAG" ] || { echo "FAIL: CLAIMS.json artifact.tag is '$want', not '$TAG' (edit CLAIMS.json or pass the right tag)"; exit 1; }
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && { echo "FAIL: tag $TAG exists; bump it (a cited revision is never moved)"; exit 1; }
[ -f docs/HANDOFF.md ] && grep -q "PetroTrack" docs/HANDOFF.md && { echo "FAIL: docs/HANDOFF.md is another project's file; git rm it first"; exit 1; }
echo "[gates]"
bash harness/macaudit/verified_bytes_gate.sh
python3 harness/macaudit/claims_gate.py --claims CLAIMS.json --scan README.md crates/runtime/README.md docs paper/main.tex paper/supplement.tex --artifact-url paper/main.tex
python3 harness/macaudit/hypothesis_gates.py --root results --check >/dev/null && echo "hypothesis_gates: OK"
python3 harness/macaudit/a7_rescore.py --check | tail -1
# placeholders are judged on the RENDERED text, not the source (comments may mention them)
for pdf in paper/main.pdf paper/supplement.pdf; do
  [ -f "$pdf" ] || { echo "FAIL: $pdf missing (build the paper first)"; exit 1; }
  if pdftotext -layout "$pdf" - | grep -q "\[pending\|until run\|\[probe 30[0-9][^]]*pending"; then
    echo "FAIL: $pdf still prints a placeholder:"; pdftotext -layout "$pdf" - | grep -n "\[pending\|until run" | head -5; exit 1; fi
done
echo "[commit + tag]"
git add -A
git commit -m "release $TAG: the revision the manuscript cites" || true
git tag -a "$TAG" -m "mac-consistency $TAG: revision cited by the manuscript (CLAIMS.json artifact.tag)"
git push && git push origin "$TAG"
echo "tagged $TAG at $(git rev-parse --short HEAD); now: python3 harness/macaudit/claims_gate.py --claims CLAIMS.json --remote-readme"
