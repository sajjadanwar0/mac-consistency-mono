// =====================================================================
// Verus proof (DRAFT, not yet run through verus in this audit -- the sandbox
// has no Verus; run `verus --crate-type=lib src/lib_l5_ledger.rs` under the
// pinned build and fix trigger/assert details before counting it):
//
//   L_5 safety for a BASIS LEDGER that prevents A_7 (superseded-basis effect)
//   under arbitrary interleaving of effect registration, writes and releases.
//
// A_7 (Guarded5.tla, SupersededBasisEffect): an effect is OUT (externalized),
// its basis -- the (cell, value) pairs its arguments were derived from, by
// argument provenance -- disagrees with the current committed value of some
// cell, and no compensation obligation has been registered for it.  A_1 is
// the window before the effect's commit; A_7 is the window after it, which
// for an irreversible effect over revisable state never closes.  "Current
// committed value" is the state-machine form of the TLA+ predicate's "latest
// post-commit writer": a value overwritten and then restored does not fire.
//
// The ledger discipline (G7): (i) an effect registers its basis when it is
// committed; (ii) a write that supersedes a basis value of an externalized
// effect registers a compensation obligation ATOMICALLY with the write;
// (iii) an effect released on a basis the store no longer agrees with gets
// its obligation at release.  The ledger never refuses a step.  What it
// guarantees is exactly inv_l5: no externalized effect has a stale basis
// without an obligation -- bounded-delay (here: zero-delay) registration,
// which Theorem 2 of the main paper argues is the strongest post-commit
// guarantee an irreversible effect admits.  How an obligation is discharged
// (rebook, cancel, ask a human) is outside the model.
//
// Modeled on lib_l4_safety.rs.  NULL is the value 0 (a modeling convention
// over int carriers, not an axiom).
//
// TRUST BASE (intended): zero axioms, zero external_body, zero assume, zero admit.
// =====================================================================

#![allow(unused_imports)]
#![allow(dead_code)]
use vstd::prelude::*;

verus! {

// vstd 0.2026.09: Map::new(dom: Set<K>, f) is uninterp; its domain/index facts come
// from the broadcast map lemmas, as in the rest of this crate (lib_l2_safety.rs).
broadcast use {vstd::map::group_map_lemmas, vstd::set::group_set_lemmas};

pub type CellId   = int;
pub type Value    = int;
pub type EffectId = int;

pub open spec fn null() -> Value { 0 }

pub struct Effect {
    /// argument provenance: cell -> the value the effect's arguments were taken from
    pub basis:        Map<CellId, Value>,
    pub externalized: bool,
    pub obligation:   bool,
}

pub struct LedgerState {
    /// current committed value per cell; absent = NULL
    pub cells:   Map<CellId, Value>,
    pub effects: Map<EffectId, Effect>,
}

pub open spec fn initial_state() -> LedgerState {
    LedgerState { cells: Map::empty(), effects: Map::empty() }
}

pub open spec fn cell_value(s: LedgerState, c: CellId) -> Value {
    if s.cells.contains_key(c) { s.cells[c] } else { null() }
}

/// the basis of `ef` disagrees with the store on some cell
pub open spec fn basis_stale(s: LedgerState, ef: Effect) -> bool {
    exists |c: CellId| #![trigger ef.basis[c]] ef.basis.contains_key(c) && cell_value(s, c) != ef.basis[c]
}

/// A_7 at the state level
pub open spec fn a7_witness(s: LedgerState, e: EffectId) -> bool {
    &&& s.effects.contains_key(e)
    &&& s.effects[e].externalized
    &&& !s.effects[e].obligation
    &&& basis_stale(s, s.effects[e])
}

// ---------------------------------------------------------------------
// Steps
// ---------------------------------------------------------------------

pub open spec fn register_valid(s: LedgerState, e: EffectId) -> bool {
    !s.effects.contains_key(e)
}

/// (i) commit an effect with its basis; `out_now` = released at commit
/// (no output commit), in which case (iii) applies at once.
pub open spec fn step_register(s: LedgerState, e: EffectId, basis: Map<CellId, Value>, out_now: bool) -> LedgerState
    recommends register_valid(s, e)
{
    let ef0 = Effect { basis: basis, externalized: false, obligation: false };
    let ef  = Effect { externalized: out_now, obligation: out_now && basis_stale(s, ef0), ..ef0 };
    LedgerState { effects: s.effects.insert(e, ef), ..s }
}

/// (ii) the obligation a write (c := v) registers on one effect
pub open spec fn mark(ef: Effect, c: CellId, v: Value) -> Effect {
    Effect {
        obligation: ef.obligation || (ef.externalized && ef.basis.contains_key(c) && ef.basis[c] != v),
        ..ef
    }
}

/// a write commits: the cell changes and every superseded externalized effect
/// is marked, atomically
pub open spec fn step_write(s: LedgerState, c: CellId, v: Value) -> LedgerState {
    LedgerState {
        cells:   s.cells.insert(c, v),
        effects: Map::new(s.effects.dom(), |e: EffectId| mark(s.effects[e], c, v)),
    }
}

/// the same write WITHOUT the ledger (the unguarded baseline)
pub open spec fn step_write_unguarded(s: LedgerState, c: CellId, v: Value) -> LedgerState {
    LedgerState { cells: s.cells.insert(c, v), ..s }
}

pub open spec fn externalize_valid(s: LedgerState, e: EffectId) -> bool {
    s.effects.contains_key(e) && !s.effects[e].externalized
}

/// (iii) release a held effect; if its basis is stale by now, register at release
pub open spec fn step_externalize(s: LedgerState, e: EffectId) -> LedgerState
    recommends externalize_valid(s, e)
{
    let ef = s.effects[e];
    let ef2 = Effect { externalized: true, obligation: ef.obligation || basis_stale(s, ef), ..ef };
    LedgerState { effects: s.effects.insert(e, ef2), ..s }
}

// ---------------------------------------------------------------------
// The invariant and its preservation by every step
// ---------------------------------------------------------------------

pub open spec fn inv_l5(s: LedgerState) -> bool {
    forall |e: EffectId| #![trigger s.effects[e]]
        s.effects.contains_key(e) && s.effects[e].externalized && basis_stale(s, s.effects[e])
        ==> s.effects[e].obligation
}

pub proof fn lemma_initial_inv_l5()
    ensures inv_l5(initial_state()),
{
    assert(initial_state().effects =~= Map::<EffectId, Effect>::empty());
}

pub proof fn lemma_register_preserves_inv_l5(s: LedgerState, e: EffectId, basis: Map<CellId, Value>, out_now: bool)
    requires inv_l5(s), register_valid(s, e),
    ensures inv_l5(step_register(s, e, basis, out_now)),
{
    let s2 = step_register(s, e, basis, out_now);
    assert(s2.cells == s.cells);
    assert forall |x: EffectId| #![trigger s2.effects[x]]
        s2.effects.contains_key(x) && s2.effects[x].externalized && basis_stale(s2, s2.effects[x])
        implies s2.effects[x].obligation
    by {
        // the store is unchanged, so staleness in s2 is staleness in s
        assert forall |c: CellId| cell_value(s2, c) == cell_value(s, c) by {}
        if x == e {
            let ef0 = Effect { basis: basis, externalized: false, obligation: false };
            assert(s2.effects[e].basis == basis);
            if out_now {
                // released at commit: obligation == basis_stale(s, ef0), and staleness
                // depends only on the basis and the (unchanged) store
                assert(basis_stale(s2, s2.effects[e]) ==> basis_stale(s, ef0));
            } else {
                assert(!s2.effects[e].externalized);
            }
        } else {
            assert(s2.effects[x] == s.effects[x]);
            assert(s.effects.contains_key(x));
            assert(basis_stale(s2, s.effects[x]) ==> basis_stale(s, s.effects[x]));
        }
    }
}

/// The load-bearing step: a write can make a basis stale, and the same step
/// registers the obligation.
pub proof fn lemma_write_preserves_inv_l5(s: LedgerState, c: CellId, v: Value)
    requires inv_l5(s),
    ensures inv_l5(step_write(s, c, v)),
{
    let s2 = step_write(s, c, v);
    assert(s2.effects.dom() == s.effects.dom());          // Map::new domain (broadcast lemma)
    assert forall |x: EffectId| #![trigger s2.effects[x]]
        s2.effects.contains_key(x) && s2.effects[x].externalized && basis_stale(s2, s2.effects[x])
        implies s2.effects[x].obligation
    by {
        assert(s.effects.contains_key(x));
        assert(s2.effects[x] == mark(s.effects[x], c, v)); // Map::new index (broadcast lemma)
        let ef = s.effects[x];
        assert(s2.effects[x].basis == ef.basis);
        assert(s2.effects[x].externalized == ef.externalized);
        // some basis cell d disagrees with the new store
        let d = choose |d: CellId| #![trigger ef.basis[d]] ef.basis.contains_key(d) && cell_value(s2, d) != ef.basis[d];
        if d == c {
            // the write itself superseded the basis: mark() registered it
            assert(cell_value(s2, c) == v);
            assert(ef.basis[c] != v);
            assert(s2.effects[x].obligation);
        } else {
            // d was already stale in s, so the obligation was already registered
            assert(cell_value(s2, d) == cell_value(s, d));
            assert(basis_stale(s, ef));
            assert(ef.obligation);
            assert(s2.effects[x].obligation);
        }
    }
}

pub proof fn lemma_externalize_preserves_inv_l5(s: LedgerState, e: EffectId)
    requires inv_l5(s), externalize_valid(s, e),
    ensures inv_l5(step_externalize(s, e)),
{
    let s2 = step_externalize(s, e);
    assert(s2.cells == s.cells);
    assert forall |x: EffectId| #![trigger s2.effects[x]]
        s2.effects.contains_key(x) && s2.effects[x].externalized && basis_stale(s2, s2.effects[x])
        implies s2.effects[x].obligation
    by {
        assert forall |c: CellId| cell_value(s2, c) == cell_value(s, c) by {}
        if x == e {
            assert(s2.effects[e].basis == s.effects[e].basis);
            assert(basis_stale(s2, s2.effects[e]) ==> basis_stale(s, s.effects[e]));
        } else {
            assert(s2.effects[x] == s.effects[x]);
            assert(s.effects.contains_key(x));
            assert(basis_stale(s2, s.effects[x]) ==> basis_stale(s, s.effects[x]));
        }
    }
}

/// THEOREM L_5: every state the ledgered runtime reaches from initial_state,
/// through any interleaving of registrations, writes and releases, satisfies
/// inv_l5 (the lemmas above), and no effect in such a state is an A_7 witness.
pub proof fn lemma_l5_no_a7(s: LedgerState)
    requires inv_l5(s),
    ensures forall |e: EffectId| #![trigger a7_witness(s, e)] !a7_witness(s, e),
{
    assert forall |e: EffectId| #![trigger a7_witness(s, e)] !a7_witness(s, e) by {
        if s.effects.contains_key(e) && s.effects[e].externalized && basis_stale(s, s.effects[e]) {
            assert(s.effects[e].obligation);
        }
    }
}

// ---------------------------------------------------------------------
// Non-vacuity
// ---------------------------------------------------------------------

/// Without the ledger: an effect derived from cell 7 = NULL is released at
/// commit; a later write 7 := 5 supersedes it; nothing registers; A_7.
pub proof fn lemma_unguarded_write_reaches_a7()
    ensures ({
        let b  = Map::<CellId, Value>::empty().insert(7, null());
        let s1 = step_register(initial_state(), 0, b, true);
        let s2 = step_write_unguarded(s1, 7, 5);
        &&& register_valid(initial_state(), 0)
        &&& inv_l5(s1)
        &&& !a7_witness(s1, 0)
        &&& a7_witness(s2, 0)
    }),
{
    let s0 = initial_state();
    let b  = Map::<CellId, Value>::empty().insert(7, null());
    let s1 = step_register(s0, 0, b, true);
    assert(s1.effects.contains_key(0));
    assert(s1.effects[0].basis == b);
    assert(s1.effects[0].externalized);
    // at commit the basis agrees with the store (cell 7 is NULL), so no obligation
    assert forall |c: CellId| #![trigger b[c]] b.contains_key(c) implies cell_value(s0, c) == b[c] by {
        assert(c == 7);
        assert(!s0.cells.contains_key(7));
    }
    let ef0 = Effect { basis: b, externalized: false, obligation: false };
    assert(!basis_stale(s0, ef0));
    assert(!s1.effects[0].obligation);
    assert(!basis_stale(s1, s1.effects[0]));
    assert(!a7_witness(s1, 0));
    assert forall |x: EffectId| #![trigger s1.effects[x]]
        s1.effects.contains_key(x) && s1.effects[x].externalized && basis_stale(s1, s1.effects[x])
        implies s1.effects[x].obligation
    by {
        assert(x == 0);
        assert(!basis_stale(s1, s1.effects[0]));
    }
    let s2 = step_write_unguarded(s1, 7, 5);
    assert(s2.effects == s1.effects);
    assert(cell_value(s2, 7) == 5);
    assert(b.contains_key(7) && cell_value(s2, 7) != b[7]);
    assert(basis_stale(s2, s2.effects[0]));
    assert(a7_witness(s2, 0));
}

/// With the ledger the same write registers the obligation, and a second
/// write that RESTORES the value leaves the obligation in place and the basis
/// current: no witness either way.
pub proof fn lemma_ledger_registers_on_supersession()
    ensures ({
        let b  = Map::<CellId, Value>::empty().insert(7, null());
        let s1 = step_register(initial_state(), 0, b, true);
        let s2 = step_write(s1, 7, 5);
        let s3 = step_write(s2, 7, null());
        &&& s2.effects[0].obligation
        &&& !a7_witness(s2, 0)
        &&& !a7_witness(s3, 0)
    }),
{
    let s0 = initial_state();
    let b  = Map::<CellId, Value>::empty().insert(7, null());
    let s1 = step_register(s0, 0, b, true);
    let s2 = step_write(s1, 7, 5);
    assert(s2.effects.contains_key(0));
    assert(s2.effects[0] == mark(s1.effects[0], 7, 5));
    assert(s1.effects[0].externalized && s1.effects[0].basis.contains_key(7) && s1.effects[0].basis[7] != 5);
    assert(s2.effects[0].obligation);
    assert(!a7_witness(s2, 0));
    let s3 = step_write(s2, 7, null());
    assert(s3.effects[0] == mark(s2.effects[0], 7, null()));
    assert(s3.effects[0].obligation);
    assert(!a7_witness(s3, 0));
}

} // verus!
