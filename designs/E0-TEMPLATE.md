# E0: Experiment Title

**Owner:** name · 
**Status:** draft | running | done · 
**Prereg:** none | link
**Budget:** est. API $ / GPU-hrs (or $0 — offline) · 
key-name: `sps-E?-slug`

## Question
One falsifiable sentence. Consider the result that would prove this wrong. 

Test: what would a negative result look like, and what would it still teach us? If a negative result teaches nothing, the experiment isn't well scoped yet.

**If positive → implies … / If negative → implies …**


## Why this experiment now
Two or three sentences: what it unblocks, what it depends on.


## Ground truth
What is *proven* vs what is *judged* (and by whom). Judged signals are never gold; write down what they are used for instead (triage, exploration, sanity).

## Out of scope
Inputs/settings where the instrument must refuse to speak, and how that refusal is exercised.

## Variations
- seeds: >=3 if anything is sampled
- models: name them (ideally 1 open + 1 closed; Lean-finetuned vs base if relevant)
- samples: pilot size (~30) before scale size
- prompts: templates held fixed across conditions; if the prompt varies with the condition, the prompt becomes the experiment.



## Compute estimate
- API calls: examples × models × seeds × prompt-variants -> rough $ at expected price
- GPU: model size, batch, layers stored if extracting activations (activations = layers × hidden × tokens × examples; it gets big fast; store selected layers)
- Wall-clock guess; Modal (pay-per-use) vs local 

## Output artifact
What remains behind when you're done? (a plot, a table, a labbeled dataset, a go/no-go for the next experiment)?