# semantic-diffchecking

**Workspace for the Secure Program Synthesis stream: instruments for semantic diffchecking.**

When a model translates intent into a formal artifact (e.g., a spec, a program, a test), the output can be perfectly well-formed and still not mean what the intent meant. Judge-style evaluation of that gap degrades under optimization pressure. In this repo we design, pilot, and scope experiments built to measure meaning preservation across artifacts.


## The fellowship

This stream runs inside [The Secure Program Synthesis Fellowship](https://apartresearch.com/fellowships/the-secure-program-synthesis-fellowship)
(June–October 2026), a partnered fellowship by Apart Research and Atlas Computing: mentor-led teams doing part-time research at the intersection of formal methods, AI systems, and security. Two research stages; workshop paper (or equivalent), then demo day / conference paper, with compute, API credits, and an Apart research project manager supporting the team.

Dates ahead:

- **July/August 2026**: mid-project presentations & milestone submissions
- **August/September 2026**: final submissions
- **September/October 2026**: demo day

The fellowship's four focus areas are Specification Elicitation,
Specification Validation, Spec-Driven Development & Evaluation
("vericoding"), and Adversarial Robustness for FM & QA Tools. This stream sits mainly in **Specification Validation**, checking whether a formal artifact captures the intent, with an edge into adversarial robustness (what happens to evaluation signals under optimization pressure).

Resources:

- [Fellowship page](https://apartresearch.com/fellowships/the-secure-program-synthesis-fellowship): program details, focus areas, FAQ
- [The Secure Program Synthesis Hackathon](https://apartresearch.com/sprints/secure-program-synthesis-hackathon-2026-05-22-to-2026-05-24) (May 22–24, 2026): the **Resources** tab collects good readings
- [Team Google Drive](https://drive.google.com/drive/folders/1eB3CmIMhiSMMRCKE0GQqaK6Cv4z61Z0I?usp=sharing): shared docs, notes, and slides


## Weeks 1–2: your experiments

The first week or two belong to you. Read the Related Work (in [Gdocs](https://docs.google.com/document/d/1d3sI772HJ6YMEpM5byhJjTuyK0kBtH4n1o0SHHDFMRQ/edit?tab=t.vyefkip4od2b)), browse the hackathon resources, poke at the problem space, then propose
experiments of your own as a [design](designs/E0-TEMPLATE.md) sheet and bring it to the group.

The suggested week-by-week plan: [ONBOARDING.md](ONBOARDING.md).


## The design-sheet workflow

1. Copy `designs/E0-TEMPLATE.md` to `designs/E<n>-short-keyname.md` and fill it in
2. Append one entry to `designs/index.json`.
<!-- 3. Open a PR; the hub page picks the sheet up automatically.

To publish the hub: repo Settings → Pages → deploy from `main`, root.
Locally: `python -m http.server` and open `http://localhost:8000/`. -->
