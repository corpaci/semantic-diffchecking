# Experiment evidence

## Code refactoring chain evidence

The archive contains the frozen plan, task requirements, evaluations, summary,
717 saved checkpoints (including 36 starting references), and the recurrence
script for the 20-hop refactoring study.

From this directory, extract the archive and reproduce the two-hop recurrence
counts with Python 3.

```sh
tar -xzf code-refactoring-chains.tar.gz
python3 code-refactoring-chains/recurrence.py
```

The script checks the saved checkpoint hashes and compares the bytes at hops
(t) and (t-2) wherever both checkpoints exist. It reports results by task,
model family, and reminder condition. The study recorded 518 exact returns
in 646 eligible comparisons.

Archive SHA-256: `09769a5b201bfea9a6f55b473c7d2b32da41119a1d18731e78d3772c9ef5f472`.

## Qwen3 translation pilot

The archive contains the frozen prompts, provider responses, oracle snapshot,
and analysis scripts for the 672-call controlled English translation pilot.

From this directory, extract the archive and run the replay with Python 3.11
or later.

```sh
tar -xzf qwen3-translation-replay.tar.gz
cd qwen3-translation-replay
python3 replay.py
python3 analyze.py experiments/agentic_drift/runs/native-random28-v1
```

The replay verifies the saved answers and reproduces all 672 oracle scores.
The analysis recomputes the finite counterexamples and the bootstrap over
source laws. Both commands run offline without an API key.

Archive SHA-256: `fcfa8fbf62066aa128bccdaecc4f70ca7f503f995d6203681222217b89d005f1`.
