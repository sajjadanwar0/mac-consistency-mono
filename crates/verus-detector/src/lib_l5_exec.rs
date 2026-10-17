// lib_l5_exec.rs
// ---------------------------------------------------------------------------
// Exec-mode L_5: an EXECUTABLE basis ledger whose bookkeeping is verified --
// the registration step is total (no superseded basis without an obligation,
// the exec form of lib_l5_ledger.rs's inv_l5), the compensator's report is
// recorded exactly as given, and the open set the ledger reports is exactly
// the set of obligations no successful compensation has closed.
//
// COMPILE
//   verus --crate-type=lib src/lib_l5_exec.rs
//
// RELATION TO THE MODEL (lib_l5_ledger.rs)
//   The model proves, over maps and arbitrary interleavings of effect
//   registration, writes and releases, that zero-delay registration keeps
//   inv_l5: no externalized effect has a stale basis without an obligation.
//   THIS file is the exec-mode counterpart, mirroring how lib_l3_exec.rs
//   relates to lib_l3_sequencer.rs: a runnable ledger whose data-structure
//   properties are machine-checked across every public operation, compiled
//   byte-identical into crates/runtime/src/l5_exec.rs and exposed over JSON
//   lines by crates/runtime/examples/l5_server.rs, so that probes/304's ledger
//   arm (--ledger exec) keeps its obligations in these bytes.
//
// WHAT IS AND IS NOT IN THESE BYTES
//   In: which effects a superseding write obliges (mark), what a
//   compensator's report does to an obligation (report), what the ledger
//   says is open (open_flags).  Out: the store hook that calls mark inside
//   the store lock (harness Python), the compensator itself (model call +
//   world), and the interning of cell and value strings to indices (the
//   bridge).  The paper's trust base lists the last three.  An effect's basis
//   is ONE (cell, value) pair here -- the probe's bookings depend on the date
//   cell alone; the model carries maps.
//
// THEOREMS (all proved of the runnable code's reachable states)
//   * mark is total:  after mark(cell, v) every effect whose basis at `cell`
//     differs from v carries an obligation (covered); cell, basis and attempts
//     are kept at every index and the obligation bit is exactly what it was or
//     set by this write (keeps_effect, obliged_after);
//   * thm_covered_no_residue: covered ==> the residue predicate's
//     "no obligation registered" conjunct is false for every such effect --
//     R = 0 by construction at the bytes, for the supersessions the store
//     reported;
//   * report records exactly the compensator's verdict: ok re-arms the effect
//     on the new value and closes the obligation; !ok leaves basis and
//     obligation as they were and counts the attempt;
//   * open_flags[i] == obligation of effect i, for every i.
//
// TRUST BASE: zero axioms, zero external_body, zero assume, zero admit.
//
// STATUS: verified count pinned at "?" until the first `verus` run on the
//   author's machine (runner step 7); zero errors required there.
// ---------------------------------------------------------------------------

#![allow(unused_imports)]
#![allow(dead_code)]
use vstd::prelude::*;

verus! {

// =====================================================================
// Section 1: the record and the properties
// =====================================================================

/// One externalized effect as the ledger knows it: the cell its arguments were
/// derived from, the value they were derived from (argument provenance), whether
/// a compensation obligation is open, and how many compensation attempts the
/// compensator has reported.
pub struct EffectRec {
    pub cell: usize,
    pub basis: usize,
    pub obligation: bool,
    pub attempts: usize,
}

/// Every effect whose basis at `cell` disagrees with the store's value `v`
/// carries an obligation.  This is inv_l5 of the model, read at one cell.
pub open spec fn covered(s: Seq<EffectRec>, cell: usize, v: usize) -> bool {
    forall|i: int| #![trigger s[i]]
        0 <= i < s.len() && s[i].cell == cell && s[i].basis != v ==> s[i].obligation
}

/// The residue predicate's ledger arm, at the bytes: effect i is out on a
/// basis the store (value v at cell) has superseded and no obligation is
/// registered for it.
pub open spec fn residue_fires(s: Seq<EffectRec>, cell: usize, v: usize, i: int) -> bool {
    0 <= i < s.len() && s[i].cell == cell && s[i].basis != v && !s[i].obligation
}

/// covered ==> the residue predicate fires nowhere: R = 0 by construction for
/// every supersession the ledger was told about.
pub proof fn thm_covered_no_residue(s: Seq<EffectRec>, cell: usize, v: usize)
    requires
        covered(s, cell, v),
    ensures
        forall|i: int| !residue_fires(s, cell, v, i),
{
    assert forall|i: int| !residue_fires(s, cell, v, i) by {
        if 0 <= i < s.len() && s[i].cell == cell && s[i].basis != v {
            assert(s[i].obligation);
        }
    }
}

/// Index j of the new state keeps the effect of the old state (cell, basis,
/// attempts): the registration step moves the obligation bit and nothing else.
pub open spec fn keeps_effect(a: Seq<EffectRec>, b: Seq<EffectRec>, j: int) -> bool {
    b[j].cell == a[j].cell && b[j].basis == a[j].basis && b[j].attempts == a[j].attempts
}

/// The obligation bit after a registration step for (cell, v): what it was, or
/// set because the effect's basis at `cell` is not v.
pub open spec fn obliged_after(a: Seq<EffectRec>, b: Seq<EffectRec>, j: int, cell: usize, v: usize) -> bool {
    b[j].obligation == (a[j].obligation || (a[j].cell == cell && a[j].basis != v))
}

// =====================================================================
// Section 2: the executable ledger
// =====================================================================

pub struct L5Ledger {
    pub effects: Vec<EffectRec>,
}

impl L5Ledger {
    pub fn new() -> (r: Self)
        ensures
            r.effects@.len() == 0,
    {
        L5Ledger { effects: Vec::new() }
    }

    /// An effect is out: record its basis.  Returns its index.
    pub fn register_effect(&mut self, cell: usize, basis: usize) -> (id: usize)
        ensures
            id == old(self).effects@.len(),
            self.effects@ == old(self).effects@.push(EffectRec { cell, basis, obligation: false, attempts: 0 }),
    {
        let id = self.effects.len();
        self.effects.push(EffectRec { cell, basis, obligation: false, attempts: 0 });
        id
    }

    /// REGISTRATION, atomic with the superseding write (the caller holds the
    /// store lock): flag every effect whose basis at `cell` the new value `v`
    /// supersedes.  Returns (fresh, retried): the indices obliged by THIS write
    /// and those whose obligation was already open (an earlier compensation
    /// failed; this supersession retries it).  No field but `obligation` moves.
    pub fn mark(&mut self, cell: usize, v: usize) -> (r: (Vec<usize>, Vec<usize>))
        ensures
            self.effects@.len() == old(self).effects@.len(),
            forall|j: int| #![trigger self.effects@[j]]
                0 <= j < self.effects@.len() ==>
                    keeps_effect(old(self).effects@, self.effects@, j)
                    && obliged_after(old(self).effects@, self.effects@, j, cell, v),
            covered(self.effects@, cell, v),
            forall|k: int| 0 <= k < r.0@.len() ==> ((#[trigger] r.0@[k]) as int) < self.effects@.len(),
            forall|k: int| 0 <= k < r.1@.len() ==> ((#[trigger] r.1@[k]) as int) < self.effects@.len(),
    {
        let mut fresh: Vec<usize> = Vec::new();
        let mut retried: Vec<usize> = Vec::new();
        let n = self.effects.len();
        let mut i: usize = 0;
        while i < n
            invariant
                i <= n,
                n == self.effects@.len(),
                n == old(self).effects@.len(),
                forall|j: int| #![trigger self.effects@[j]]
                    0 <= j < n ==> keeps_effect(old(self).effects@, self.effects@, j),
                forall|j: int| #![trigger self.effects@[j]]
                    0 <= j < i ==> obliged_after(old(self).effects@, self.effects@, j, cell, v),
                forall|j: int| #![trigger self.effects@[j]]
                    i <= j < n ==> self.effects@[j].obligation == old(self).effects@[j].obligation,
                forall|k: int| 0 <= k < fresh@.len() ==> ((#[trigger] fresh@[k]) as int) < i as int,
                forall|k: int| 0 <= k < retried@.len() ==> ((#[trigger] retried@[k]) as int) < i as int,
            decreases n - i,
        {
            let c = self.effects[i].cell;
            let b = self.effects[i].basis;
            let o = self.effects[i].obligation;
            let a = self.effects[i].attempts;
            if c == cell && b != v {
                if o {
                    retried.push(i);
                } else {
                    fresh.push(i);
                    self.effects.set(i, EffectRec { cell: c, basis: b, obligation: true, attempts: a });
                }
            }
            i = i + 1;
        }
        // the registration is total: every superseded basis now carries an obligation
        assert forall|j: int| #![trigger self.effects@[j]]
            0 <= j < self.effects@.len() && self.effects@[j].cell == cell && self.effects@[j].basis != v
            implies self.effects@[j].obligation by {
            assert(keeps_effect(old(self).effects@, self.effects@, j));
            assert(obliged_after(old(self).effects@, self.effects@, j, cell, v));
        }
        (fresh, retried)
    }

    /// The compensator's report on obligation `i` after a supersession to `v`:
    /// `ok` (every step of the compensation succeeded) closes the obligation
    /// and re-arms the effect on the new value -- the replacement is a fresh
    /// effect with a current basis, owed a further obligation by a further
    /// revision; `!ok` (the world refused a step) leaves basis and obligation
    /// exactly as they were.  Either way the attempt is counted.
    pub fn report(&mut self, i: usize, v: usize, ok: bool)
        requires
            i < old(self).effects@.len(),
            old(self).effects@[i as int].attempts < usize::MAX,
        ensures
            self.effects@.len() == old(self).effects@.len(),
            forall|j: int| #![trigger self.effects@[j]]
                0 <= j < self.effects@.len() && j != i as int ==> self.effects@[j] == old(self).effects@[j],
            self.effects@[i as int].cell == old(self).effects@[i as int].cell,
            self.effects@[i as int].attempts == old(self).effects@[i as int].attempts + 1,
            ok ==> self.effects@[i as int].basis == v && !self.effects@[i as int].obligation,
            !ok ==> self.effects@[i as int].basis == old(self).effects@[i as int].basis
                    && self.effects@[i as int].obligation == old(self).effects@[i as int].obligation,
    {
        let c = self.effects[i].cell;
        let b = self.effects[i].basis;
        let o = self.effects[i].obligation;
        let a = self.effects[i].attempts;
        if ok {
            self.effects.set(i, EffectRec { cell: c, basis: v, obligation: false, attempts: a + 1 });
        } else {
            self.effects.set(i, EffectRec { cell: c, basis: b, obligation: o, attempts: a + 1 });
        }
    }

    /// What the ledger reports open: flag i is the obligation bit of effect i.
    pub fn open_flags(&self) -> (f: Vec<bool>)
        ensures
            f@.len() == self.effects@.len(),
            forall|j: int| #![trigger f@[j]]
                0 <= j < f@.len() ==> f@[j] == self.effects@[j].obligation,
    {
        let mut f: Vec<bool> = Vec::new();
        let n = self.effects.len();
        let mut i: usize = 0;
        while i < n
            invariant
                i <= n,
                n == self.effects@.len(),
                f@.len() == i as int,
                forall|j: int| #![trigger f@[j]]
                    0 <= j < i ==> f@[j] == self.effects@[j].obligation,
            decreases n - i,
        {
            let o = self.effects[i].obligation;
            f.push(o);
            i = i + 1;
        }
        f
    }

    /// Number of effects the ledger holds.
    pub fn len(&self) -> (n: usize)
        ensures
            n == self.effects@.len(),
    {
        self.effects.len()
    }
}

// =====================================================================
// Section 3: non-vacuity -- the prevented phenomenon exists at this
// representation: an effect out on a superseded basis with no obligation
// =====================================================================

pub proof fn lemma_unledgered_admits_residue()
    ensures
        exists|s: Seq<EffectRec>| #[trigger] residue_fires(s, 1usize, 2usize, 0),
{
    let s: Seq<EffectRec> = seq![EffectRec { cell: 1usize, basis: 1usize, obligation: false, attempts: 0usize }];
    assert(s.len() == 1);
    assert(s[0].cell == 1usize && s[0].basis == 1usize && !s[0].obligation);
    assert(residue_fires(s, 1usize, 2usize, 0));
}

} // verus!
