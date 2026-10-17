#!/usr/bin/env bash
# verified_bytes_gate.sh -- "the verified code is the code measured" is a claim about
# BYTES; this gate makes it checkable.  Every file the runtime crate compiles with
# plain cargo (proofs erased) must be byte-identical to the file the pinned Verus
# build verified.  Exit 1 on the first difference.  Run before every submission and
# in reproduce.sh.
#
#   bash harness/macaudit/verified_bytes_gate.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
V=crates/verus-detector/src; R=crates/runtime/src
pairs=(
  "$V/lib_l2_exec.rs          $R/l2_exec.rs          L2 output commit (73 obligations)"
  "$V/lib_l4_exec.rs          $R/l4_exec.rs          L4 validation at dispatch (11)"
  "$V/lib_si_concurrent.rs    $R/si_concurrent.rs    L1 SI store on the verified lock (18)"
  "$V/lib_pess_concurrent.rs  $R/pess_concurrent.rs  L1 pessimistic store on the verified lock (31)"
  "$V/lib_detect_a1_exec.rs   $R/detect_a1_exec.rs   A1 detector, exec mode (9) -- the scorer's A1 verdict"
  "$V/lib_l3_exec.rs          $R/l3_exec.rs          L3 sequencer, exec mode (7) -- behind examples/l3_server.rs"
  "$V/lib_l5_exec.rs          $R/l5_exec.rs          L5 basis ledger, exec mode (?) -- behind examples/l5_server.rs (probes/304 --ledger exec)"
)
bad=0
for p in "${pairs[@]}"; do
  set -- $p; a=$1; b=$2; shift 2; what="$*"
  if [ ! -f "$a" ] || [ ! -f "$b" ]; then echo "MISSING  $a / $b  ($what)"; bad=1; continue; fi
  ha=$(sha256sum "$a" | cut -c1-16); hb=$(sha256sum "$b" | cut -c1-16)
  if [ "$ha" = "$hb" ]; then echo "identical $ha  $b  <- $a  ($what)"; else echo "DIFFER    $ha != $hb  $b vs $a  ($what)"; bad=1; fi
done
# the one piece of unverified code between the verified A1 bytes and the string-valued records
echo "trusted   $(sha256sum $R/detect_a1_verified.rs | cut -c1-16)  $R/detect_a1_verified.rs  (interning wrapper: in the trust base, listed in the paper)"
[ $bad = 0 ] && echo "OK: every measured verified file is byte-identical to its verified source" || { echo "FAIL: a measured file differs from its verified source"; exit 1; }
