# Suggested first three weeks

The onboarding task spans the first three weeks. Each week should produce
an artifact that becomes the input to the following week.

## Ground rules :D

- "No proof or counterexample found" is not evidence of equivalence; we
  label as "unknown"
- Record everything: provider, model, version, prompt, parameters,
  timestamp, annotators, etc
- Judged signals are not gold.
- Budget:


## Week 1: Understand the semantic oracle and construct the dataset

Read:

- the Equational Theories Project overview,
- Translation Validation,
- The Faithfulness Gap,
- and the Task Description.

Write a short description of the following semantic relation labels in
your own words: equivalent, weaker, stronger, incomparable,
outside-fragment, and unknown.

### Explore the tools

Explore the ETP equation, implication graph, and finite magma tools.
Learn how to:

- retrieve an equation,
- inspect implication relationships,
- identify stronger, weaker, and incomparable theories,
- normalize variable names and notation,
- and validate a finite magma counterexample.

### Construct representation pairs

Choose 20+ equations from the Equational Theories Project. Include a
mixture of:

- simple and complex equations,
- familiar and obscure laws,
- equations with repeated variables,
- equations with different tree structures,
- and theories with nearby stronger, weaker, or incomparable alternatives.

For each equation:

- Write or generate one natural language description.
- Ask at least one LLM to translate it back into a formal equation.
- Manually inspect and normalize the generated equation.
- Check whether it maps to an ETP node.
- Compare it with the intended equation using the formal semantic oracle
  where possible.
- Record parsing failures, outside-fragment outputs, unknown cases, and
  syntactically valid but semantically unfaithful outputs.

For at least 3 equations, construct one controlled semantic mutation,
such as: variable replacement, subtree deletion, changed parentheses,
weakening, strengthening, or replacement with a nearby ETP law.

### Deliverable

A labeled dataset of 20 to 50 intended and generated equation pairs.
Include:

- intended equations,
- natural language descriptions,
- generated equations,
- normalized equations,
- ETP node matches,
- semantic relations,
- oracle/evidence used,
- and notes on uncertain cases.

### Main questions

- What kinds of semantic drift appear in LLM-generated translations?
- Which outputs cannot be resolved using the current semantic oracle?


## Week 2: Implement and compare initial semantic diff metrics

Read further from the Related Work tab Apart/SPS - Notes

Select at least two approximate metrics and compare them with the formal
semantic oracle. Possible metrics include:

- exact string match,
- normalized syntax match,
- edit distance,
- embedding similarity,
- and LLM self-evaluation.

For each representation pair, record:

- the metric output,
- the raw score where applicable,
- the predicted semantic relation,
- the evidence or explanation produced,
- and whether it agrees with the formal oracle.

Separate the formal oracle from the approximate baselines. The formal
oracle may use the ETP implication graph lookup where both equations map
to ETP nodes, Lean proofs, or finite counterexamples. Failure to find a
proof or counterexample should label to unknown.

### Deliverable

A results table comparing at least two approximate metrics with the
formal semantic relation. Include things like:

- overall accuracy,
- results by semantic relation,
- unresolved cases,
- false equivalence judgments,
- and examples where metrics disagree.

### Main questions

- Which semantic differences does each metric detect or miss?
- Which metrics are robust to surface changes such as renaming or
  notation changes?
- Which metrics confuse syntactic similarity with semantic preservation?


## Week 3: Analyze disagreements and generate research proposals

Identify at least three informative cases where:

- two approximate metrics disagree,
- an approximate metric disagrees with the formal oracle,
- a controlled mutation is missed,
- a naturally occurring LLM failure is accepted,
- or the semantic relation remains unknown.

For each case, explain:

- what semantic difference occurred,
- what each metric predicted,
- why the metrics may have disagreed,
- what evidence would resolve the disagreement,
- and whether the case suggests a broader failure pattern
  [optional thought exercise]

Use these cases to develop three testable follow-up research proposals.
Each proposal should include:

- research question,
- hypothesis,
- experiment,
- data required,
- semantic diff metric,
- baseline,
- ground truth,
- expected failure mode,
- minimum viable test,
- and what a negative result would mean.

### Deliverable

An analysis of at least three metric disagreements and three testable
research proposals.

### Main question

Which observed disagreement supports the clearest, most informative, and
most feasible next experiment?


## Expected Output

At the end of Week 3, we should have produced:

- a small dataset of representation pairs,
- a table of semantic relation, outside-fragment, and unknown labels,
- results from at least two approximate semantic diff metrics,
- at least three informative metric disagreement cases,
- one comparison between the formal semantic oracle and a weaker baseline,
- and three follow-up research proposals.

The output does not need to be polished, but it should be sufficient to
support a decision about which research direction is most promising.
