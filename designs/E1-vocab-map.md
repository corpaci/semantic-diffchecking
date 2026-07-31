# E1: One relation vocabulary across ETP and LADR

**Owner:** Luiza Corpaci (ETP) · Ke Zhang (LADR) · 
**Status:** draft · 
**Prereg:** none (freeze this sheet before the first joint annotation pass)
**Budget:** $0 — offline; existing annotations only · 
key-name: `sps-E1-vocab-map`

## Question

**Every LADR drift class is either determined by the ETP relation label or falls into a
small, enumerable, named residual — with nothing left over.**

If that holds, a metric's error profile measured on ETP transfers to LADR by
*relabeling*, and the ETP track is a screening instrument for RQ3. If it does not
hold, the two tracks measure incommensurable things and each must be calibrated
separately.

Test: hand-map the pilot-27 annotated LADR items (human `faithfulness` +
`drift_classes` already exist) and the 22 ETP pairs through the table in
§Mapping, in both directions. Count items that land in the residual, and check
whether the residual is *structured* (falls into the named buckets below) or
*scattered*.

A negative result is informative and cheap: it tells us before spending
annotation hours that "extrapolate our current methods to the wild" needs a
different bridge than a shared label set — most likely a per-drift-class
calibration instead of a single transfer function.

**If positive → ETP is a screening instrument: a metric that fails the directional
test on magmas is retired before it ever reaches Lean, and cross-track
precision/recall tables are comparable.
If negative → ETP results stand alone; the LADR meta-evaluation must build its own
baselines, and the two tracks share tooling but not conclusions.**

## Why this experiment now

Nothing else in the joint program can be specified until the two label sets are
reconciled: a shared `metrics/` module needs one output vocabulary, and the
cross-track results table needs one set of columns. It is also the cheapest
experiment we have — no API spend, no new annotation, only re-reading labels that
already exist — so it should not sit behind anything.

## Ground truth

**Proven.** The ETP side. `equivalent / weaker / stronger / incomparable` come off
the resolved implication matrix and are backed by Lean proofs or verified
counterexample magmas; `unknown` is the 190 unsettled cells. Nothing here is
judged.

**Judged.** The LADR side. `faithfulness` and `drift_classes` are human verdicts
against the book-intended meaning (statement ⊕ chapter scope ⊕ book definitions),
with κ reported. Used here to *define* the mapping, never as gold for a metric.

**Judged, and kept separate.** The mapping itself is a human artifact. Two people
map independently; disagreements are the finding, not noise to be averaged away.

### Direction convention (state once; easy to invert)

Both tracks adopt the oracle's convention, stated relative to the **generated**
artifact:

- **weaker** = intended ⇒ generated. The generated artifact is a consequence of
  the intended one; it claims less. In Lean: a hypothesis was **added**.
- **stronger** = generated ⇒ intended. The generated artifact claims more. In
  Lean: a hypothesis was **dropped**, or a type was **generalized**.

Sanity anchors: ETP `x = x` (E1) is the weakest law — every magma satisfies it.
`x = y` (E2) is the strongest — only the trivial magma does. A Lean statement over
an arbitrary `Field 𝕜` is **stronger** than the same statement over 𝔽 ∈ {ℝ, ℂ}.

## Mapping

### Faithfulness scale → lattice

| LADR `faithfulness` | ETP relation | note |
|---|---|---|
| `faithful` | `equivalent` | the only clean cell |
| `minor_drift` | `stronger` | "benign generalization": book statement is a literal instance of the Lean one |
| `major_drift` | `weaker` / `stronger` / `incomparable` | direction alone does not separate this from `minor_drift` — see Residual R1 |

### Drift classes → lattice

| drift class | ETP relation | confidence in the mapping |
|---|---|---|
| `scope_findim` | **stronger** — chapter-head assumption dropped, so the statement claims more | high |
| `scope_structure` | **stronger** — same shape | high |
| `scope_field` | **split**: *generalized* → stronger; *instantiated too narrowly* → weaker | the class must be split before it maps |
| `hyp_drift` | **split**: dropped → stronger; added → weaker; strengthened → stronger | as defined, spans two cells |
| `def_mismatch` | usually `incomparable`; **weaker** when the swap only adds a side condition (e.g. `chap_7_82` adding `CompleteSpace`) | medium |
| `concl_drift` | usually `incomparable` | medium |
| `quantifier` | **not** automatically incomparable — ∃∀ ⇒ ∀∃, so reordering is often directional; scope changes can be either | low, needs sub-classing |
| `vacuous_trivial` | **weaker**, degenerate — a vacuously true statement is implied by everything. ETP analogue: E1 | high |

Two classes need splitting before the mapping is total: `scope_field` and
`hyp_drift`. `quantifier` needs sub-classing. That is a concrete revision to
taxonomy v1.1 and should land at the same time as the pilot-30 freeze.

### Refusal tier — both instruments already have one

| ETP | LADR | shared reporting |
|---|---|---|
| `parse-failure` | malformed output | instrument could not read it |
| `outside-fragment` | — | read fine, outside the catalogue |
| — | compile-failure pool | read fine, Lean rejected it |
| `unknown` | — | in-scope, evidence absent |

Both tracks must report the refusal tier as a first-class outcome rather than
dropping it, and with the same column names. Note the ETP track's current numbers
were 32% parse-failure until the `strip_noise` fix — a refusal tier that is not
reported as a tier silently becomes a result.

### Residual — what the lattice provably cannot carry

**R1 — benign vs fatal strengthening.** Generalizing 𝔽 to an arbitrary field and
dropping a load-bearing finite-dimensionality hypothesis are *both* `stronger`.
The separating criterion ("book statement is a literal instance AND no scope fact
is load-bearing") is not in the lattice. Any metric calibrated on ETP inherits
this blind spot.

**R2 — soundness.** Every ETP law is satisfiable by some magma; the lattice orders
claims without evaluating truth. A drifted Lean statement can be outright false.
`major_drift` includes cases with no ETP analogue at all.

**R3 — referent dependence.** The `scope_*` classes exist because the intended
meaning is compositional (statement ⊕ scope ⊕ definitions). An ETP intended
meaning is a self-contained catalogue line. ETP structurally cannot exhibit scope
drift — it can only test whether a metric detects the *directional* change that
scope drift produces.

**R4 — definitional identity.** `def_mismatch` presupposes a definition library.
ETP has one operation and no definitions.

**R5 — multi-label.** `drift_classes` is multi-label; the oracle emits exactly one
relation. An item that is both `scope_findim` and `concl_drift` collapses to one
lattice cell.

**R6 — two kinds of "not sure", which must never be merged.** ETP `unknown` is a
fact about the proof corpus (190 unsettled cells). LADR `confidence: low` is a
fact about the annotator. A shared schema that folds them into one column would
make the fellowship's own ground rule — "no proof or counterexample found is not
evidence of equivalence" — unenforceable.

## Out of scope

The mapping must refuse to speak, and the refusal must be visible:

- Items in either refusal tier (parse-failure, outside-fragment, compile-failure)
  are **not** force-mapped. They are counted and reported.
- Items whose LADR label set is multi-class (R5) are routed to the residual, not
  assigned a "primary" class by tiebreak.
- Any drift class the mapper cannot place goes to the residual with a written
  reason. **A residual of zero is a failure signal, not a success** — it means the
  mapper was resolving ambiguity silently.

Refusal is exercised by pre-registering the residual buckets R1–R6 *before*
mapping and requiring every unmapped item to name one, or force a new bucket.

## Variations

- **mappers:** ≥2, independent, no discussion until both passes are complete;
  report Cohen's κ on the lattice cell and on residual-vs-mapped
- **items:** all 27 pilot LADR items + all 22 ETP rows; stratified report by
  scope-dependent (ch. 6–9) vs self-contained (ch. 1–3)
- **directions:** both — LADR→ETP (does a drift class predict a lattice cell?) and
  ETP→LADR (does a lattice cell predict a drift class?). Asymmetry between the two
  is itself a result
- **seeds / models / prompts:** none — no sampling, no generation. If an LLM is
  used to pre-fill a first pass, it is triage only, its output is never the label,
  and both human passes still run

## Compute estimate

- **API calls:** 0. Optional LLM pre-fill for triage ≈ 50 calls ≈ $1, not
  load-bearing.
- **GPU:** none.
- **Human:** ~2 h per mapper for 49 items, plus ~1 h reconciliation. Two mappers →
  ~5 h total. This is the entire cost.
- **Wall-clock:** one sitting each, one joint session.

## Output artifact

1. `designs/E1-vocab-map.md` (this sheet) with §Mapping updated to the reconciled
   version and κ recorded.
2. A `relation_vocabulary.md` reference committed at the repo root, owned by
   neither track, that both `oracle/` and `ladr/` cite — the single definition of
   `equivalent / weaker / stronger / incomparable / outside-fragment / unknown`
   and their LADR correspondences, including the direction convention above.
3. A column spec for the shared results table: which columns both tracks emit,
   which are track-specific, and the R6 rule keeping oracle-uncertainty and
   annotator-uncertainty in separate columns.
4. A go/no-go for the shared `metrics/` module: if the residual is structured, the
   module emits one vocabulary and cross-track comparison is valid; if not, the
   module still shares implementations but the tracks report separately.
5. A concrete revision request against LADR taxonomy v1.1: split `scope_field` and
   `hyp_drift` by direction, sub-class `quantifier`.
