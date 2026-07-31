#!/usr/bin/env python3
"""Build a local HTML view for comparing LADR pilot outputs and cards."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backtranslate_lean_statements import DEFAULT_ROOT, load_jsonl, source_items


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CARDS = DEFAULT_ROOT / "backtranslation" / "lean_statement_backtranslation_cards.jsonl"
DEFAULT_OUTPUT = DEFAULT_ROOT / "backtranslation" / "pilot_27_comparison.html"

COLUMNS = [
    ("one_shot_statement_only", "One-shot A", "statement only"),
    ("one_shot_statement_plus_proof", "One-shot B", "statement + proof"),
    ("repair_agent_statement_only", "Repair A", "statement only + feedback"),
    ("repair_agent_statement_plus_proof", "Repair B", "statement + proof + feedback"),
    ("multistage_skeleton", "Multistage C", "proof skeleton -> statement"),
]


def card_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("theorem_dataset_name") or ""),
        str(record.get("experiment_id") or ""),
        str(record.get("lean_statement_sha256") or ""),
    )


def load_cards(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    cards: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in load_jsonl(path):
        if record.get("status") == "ok" and isinstance(record.get("card"), dict):
            cards[card_key(record)] = record
    return cards


def build_data(root: Path, cards_path: Path) -> dict[str, Any]:
    items = source_items(root)
    cards = load_cards(cards_path)

    theorem_rows: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item["theorem_dataset_name"]
        input_row = item.get("input_row") or {}
        row = theorem_rows.setdefault(
            name,
            {
                "name": name,
                "nl_statement": input_row.get("nl_statement") or "",
                "informal_proof": input_row.get("informal_proof") or "",
                "experiments": {},
            },
        )
        key = (name, item["experiment_id"], item.get("lean_statement_sha256") or "")
        card_record = cards.get(key)
        experiment = {
            "experiment_id": item["experiment_id"],
            "source": item["source"],
            "condition": item["condition"],
            "status": item.get("status"),
            "lean_typechecked": bool(item.get("lean_typechecked")),
            "attempt_count": item.get("attempt_count"),
            "stage_statuses": item.get("stage_statuses"),
            "lean_statement": item.get("lean_statement") or "",
            "skeleton_output_text": item.get("skeleton_output_text") or "",
            "lean_statement_sha256": item.get("lean_statement_sha256") or "",
            "card_status": card_record.get("status") if card_record else None,
            "card": card_record.get("card") if card_record else None,
        }
        row["experiments"][item["experiment_id"]] = experiment

    summary: dict[str, Any] = {}
    for column_id, _, _ in COLUMNS:
        column_items = [row["experiments"].get(column_id) for row in theorem_rows.values()]
        present = [item for item in column_items if item]
        summary[column_id] = {
            "present": len(present),
            "compiled": sum(1 for item in present if item.get("lean_typechecked")),
            "cards": sum(1 for item in present if item.get("card")),
            "statuses": dict(Counter(str(item.get("status")) for item in present)),
        }

    c_success = sum(
        1
        for row in theorem_rows.values()
        if row["experiments"].get("multistage_skeleton", {}).get("lean_typechecked")
    )
    return {
        "columns": [
            {"id": column_id, "title": title, "subtitle": subtitle}
            for column_id, title, subtitle in COLUMNS
        ],
        "summary": summary,
        "c_success_count": c_success,
        "theorems": [theorem_rows[name] for name in sorted(theorem_rows)],
    }


def html_document(data: dict[str, Any]) -> str:
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LADR Pilot 27 Comparison</title>
  <style>
    :root {{
      --bg: #f7f7f4;
      --panel: #ffffff;
      --ink: #1d2528;
      --muted: #667074;
      --line: #d9dedb;
      --ok: #0f7b53;
      --bad: #b42318;
      --warn: #a15c00;
      --accent: #285e8e;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--ink); }}
    header {{ position: sticky; top: 0; z-index: 3; background: rgba(247,247,244,.96); border-bottom: 1px solid var(--line); padding: 14px 18px; }}
    h1 {{ margin: 0 0 8px; font-size: 20px; }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center; }}
    input[type="search"] {{ width: 320px; max-width: 100%; padding: 7px 9px; border: 1px solid var(--line); border-radius: 6px; background: white; }}
    label {{ color: var(--muted); }}
    button {{ padding: 7px 10px; border: 1px solid var(--line); border-radius: 6px; background: white; cursor: pointer; }}
    main {{ padding: 18px; }}
    .summary {{ display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)); gap: 10px; margin-bottom: 18px; }}
    .summary-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px; }}
    .summary-card b {{ display: block; margin-bottom: 4px; }}
    .theorem {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; margin-bottom: 18px; overflow: hidden; }}
    .theorem-head {{ padding: 12px 14px; border-bottom: 1px solid var(--line); }}
    .theorem-head h2 {{ margin: 0 0 6px; font-size: 16px; }}
    .original {{ white-space: pre-wrap; color: #2d3639; }}
    details {{ margin-top: 8px; }}
    summary {{ cursor: pointer; color: var(--accent); }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(320px, 1fr)); gap: 0; overflow-x: auto; }}
    .cell {{ min-width: 320px; border-right: 1px solid var(--line); padding: 12px; }}
    .cell:last-child {{ border-right: 0; }}
    .col-title {{ font-weight: 700; margin-bottom: 2px; }}
    .col-subtitle {{ color: var(--muted); font-size: 12px; margin-bottom: 8px; }}
    .pill {{ display: inline-block; padding: 2px 7px; border-radius: 999px; font-size: 12px; margin-right: 4px; border: 1px solid var(--line); }}
    .ok {{ color: var(--ok); background: #edf8f3; border-color: #b8decf; }}
    .bad {{ color: var(--bad); background: #fff0ee; border-color: #f2b8b1; }}
    .warn {{ color: var(--warn); background: #fff8e6; border-color: #ead69d; }}
    .missing {{ color: var(--muted); background: #f1f2f1; }}
    .card-block {{ margin-top: 10px; }}
    .card-block h4 {{ margin: 10px 0 4px; font-size: 13px; }}
    .card-block p {{ margin: 4px 0; }}
    ul {{ margin: 4px 0 8px 18px; padding: 0; }}
    pre {{ white-space: pre-wrap; overflow-x: auto; background: #f5f6f5; border: 1px solid var(--line); border-radius: 6px; padding: 8px; font-size: 12px; }}
    select, textarea {{ width: 100%; border: 1px solid var(--line); border-radius: 6px; padding: 6px; background: white; }}
    textarea {{ min-height: 58px; resize: vertical; margin-top: 6px; }}
    .audit {{ margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--line); }}
    .hidden {{ display: none; }}
    .plain {{ margin-top: 10px; font-size: 14px; }}
    .compare-select {{ padding: 7px; border: 1px solid var(--line); border-radius: 6px; background: white; }}
    @media (max-width: 1000px) {{ .summary {{ grid-template-columns: repeat(2, minmax(160px, 1fr)); }} }}
  </style>
</head>
<body>
  <header>
    <h1>LADR Pilot 27 Comparison</h1>
    <div class="toolbar">
      <input id="search" type="search" placeholder="Search theorem id or statement">
      <select id="compareMode" class="compare-select">
        <option value="repair_ab">Repair A vs Repair B</option>
        <option value="oneshot_ab">One-shot A vs One-shot B</option>
        <option value="proof_vs_multistage">Repair B vs Multistage C</option>
        <option value="all">All five columns</option>
      </select>
      <label><input id="cSuccessOnly" type="checkbox"> C-success only</label>
      <label><input id="withCardsOnly" type="checkbox"> with any back-translation card</label>
      <button id="exportJson">Export audit JSON</button>
      <button id="exportCsv">Export audit CSV</button>
    </div>
  </header>
  <main>
    <section id="summary" class="summary"></section>
    <section id="theorems"></section>
  </main>
  <script id="pilot-data" type="application/json">{data_json}</script>
  <script>
    const data = JSON.parse(document.getElementById('pilot-data').textContent);
    const labelOptions = ['', 'faithful', 'weakened', 'strengthened', 'incomparable', 'trivial_or_vacuous', 'unclear'];
    const auditKey = 'ladr-pilot-27-audit-v1';
    let audit = JSON.parse(localStorage.getItem(auditKey) || '{{}}');
    const compareModes = {{
      repair_ab: ['repair_agent_statement_only', 'repair_agent_statement_plus_proof'],
      oneshot_ab: ['one_shot_statement_only', 'one_shot_statement_plus_proof'],
      proof_vs_multistage: ['repair_agent_statement_plus_proof', 'multistage_skeleton'],
      all: data.columns.map(col => col.id),
    }};

    function saveAudit() {{ localStorage.setItem(auditKey, JSON.stringify(audit)); }}
    function esc(value) {{ return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch])); }}
    function list(items) {{ return Array.isArray(items) && items.length ? '<ul>' + items.map(x => `<li>${{esc(x)}}</li>`).join('') + '</ul>' : '<p class="muted">none listed</p>'; }}
    function statusPill(exp) {{
      if (!exp) return '<span class="pill missing">not run</span>';
      if (exp.lean_typechecked) return '<span class="pill ok">compiled</span>';
      if (exp.status === 'skipped') return '<span class="pill warn">skipped</span>';
      return '<span class="pill bad">failed</span>';
    }}
    function cardHtml(card) {{
      if (!card) return '<div class="card-block"><span class="pill missing">no card yet</span></div>';
      const hints = card.comparison_hints || {{}};
      return `<div class="card-block">
        <span class="pill ok">card</span>
        <span class="pill">${{esc(card.suggested_audit_label || 'no suggestion')}}</span>
        <p class="plain">${{esc(card.lean_plain_english)}}</p>
        <details><summary>Details</summary>
          <h4>Objects</h4>${{list(card.objects)}}
          <h4>Assumptions</h4>${{list(card.assumptions)}}
          <h4>Conclusion</h4><p>${{esc(card.conclusion)}}</p>
          <h4>Quantifiers</h4><p>${{esc(card.quantifiers)}}</p>
          <h4>Missing From Generated</h4>${{list(hints.missing_from_generated)}}
          <h4>Extra In Generated</h4>${{list(hints.extra_in_generated)}}
          <h4>Changed Or Ambiguous</h4>${{list(hints.changed_or_ambiguous)}}
          <h4>Red Flags</h4>${{list(hints.red_flags)}}
        </details>
      </div>`;
    }}
    function auditControls(theorem, expId) {{
      const key = `${{theorem}}|${{expId}}`;
      const value = audit[key] || {{label: '', note: ''}};
      const options = labelOptions.map(opt => `<option value="${{opt}}" ${{opt === value.label ? 'selected' : ''}}>${{opt || 'manual label...'}}</option>`).join('');
      return `<div class="audit" data-key="${{esc(key)}}">
        <select class="audit-label">${{options}}</select>
        <textarea class="audit-note" placeholder="Your note...">${{esc(value.note)}}</textarea>
      </div>`;
    }}
    function experimentCell(row, col) {{
      const exp = row.experiments[col.id];
      let body = `<div class="col-title">${{esc(col.title)}}</div><div class="col-subtitle">${{esc(col.subtitle)}}</div>`;
      body += statusPill(exp);
      if (!exp) return `<div class="cell">${{body}}</div>`;
      if (exp.attempt_count != null) body += `<span class="pill">attempts ${{esc(exp.attempt_count)}}</span>`;
      if (exp.stage_statuses) body += `<pre>${{esc(JSON.stringify(exp.stage_statuses, null, 2))}}</pre>`;
      body += cardHtml(exp.card);
      body += auditControls(row.name, col.id);
      if (exp.lean_statement) body += `<details><summary>Lean statement</summary><pre>${{esc(exp.lean_statement)}}</pre></details>`;
      if (exp.skeleton_output_text) body += `<details><summary>Stage 1 skeleton</summary><pre>${{esc(exp.skeleton_output_text)}}</pre></details>`;
      return `<div class="cell">${{body}}</div>`;
    }}
    function renderSummary() {{
      document.getElementById('summary').innerHTML = data.columns.map(col => {{
        const s = data.summary[col.id] || {{}};
        return `<div class="summary-card"><b>${{esc(col.title)}}</b>
          <div>${{esc(col.subtitle)}}</div>
          <div>present: ${{s.present || 0}}</div>
          <div>compiled: ${{s.compiled || 0}}</div>
          <div>cards: ${{s.cards || 0}}</div>
        </div>`;
      }}).join('');
    }}
    function theoremHasCard(row) {{ return Object.values(row.experiments).some(exp => exp && exp.card); }}
    function theoremCSuccess(row) {{ return row.experiments.multistage_skeleton && row.experiments.multistage_skeleton.lean_typechecked; }}
    function renderTheorems() {{
      const q = document.getElementById('search').value.toLowerCase();
      const cOnly = document.getElementById('cSuccessOnly').checked;
      const cardsOnly = document.getElementById('withCardsOnly').checked;
      const selectedColumns = compareModes[document.getElementById('compareMode').value] || compareModes.repair_ab;
      const columns = data.columns.filter(col => selectedColumns.includes(col.id));
      const rows = data.theorems.filter(row => {{
        if (cOnly && !theoremCSuccess(row)) return false;
        if (cardsOnly && !theoremHasCard(row)) return false;
        const haystack = `${{row.name}} ${{row.nl_statement}}`.toLowerCase();
        return !q || haystack.includes(q);
      }});
      document.getElementById('theorems').innerHTML = rows.map(row => `<article class="theorem">
        <div class="theorem-head">
          <h2>${{esc(row.name)}}</h2>
        </div>
        <div class="grid" style="grid-template-columns: repeat(${{columns.length}}, minmax(320px, 1fr));">${{columns.map(col => experimentCell(row, col)).join('')}}</div>
      </article>`).join('');
      bindAuditControls();
    }}
    function bindAuditControls() {{
      document.querySelectorAll('.audit').forEach(node => {{
        const key = node.dataset.key;
        const select = node.querySelector('.audit-label');
        const note = node.querySelector('.audit-note');
        function update() {{ audit[key] = {{label: select.value, note: note.value}}; saveAudit(); }}
        select.addEventListener('change', update);
        note.addEventListener('input', update);
      }});
    }}
    function download(name, text, type) {{
      const blob = new Blob([text], {{type}});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
    }}
    document.getElementById('exportJson').addEventListener('click', () => download('ladr_pilot_27_audit.json', JSON.stringify(audit, null, 2), 'application/json'));
    document.getElementById('exportCsv').addEventListener('click', () => {{
      const rows = [['theorem','experiment','label','note']];
      Object.entries(audit).forEach(([key, value]) => {{
        const [theorem, experiment] = key.split('|');
        rows.push([theorem, experiment, value.label || '', value.note || '']);
      }});
      const csv = rows.map(row => row.map(x => `"${{String(x).replaceAll('"','""')}}"`).join(',')).join('\\n');
      download('ladr_pilot_27_audit.csv', csv, 'text/csv');
    }});
    ['search', 'compareMode', 'cSuccessOnly', 'withCardsOnly'].forEach(id => document.getElementById(id).addEventListener('input', renderTheorems));
    renderSummary();
    renderTheorems();
  </script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local HTML comparison page for the LADR pilot.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root if args.root.is_absolute() else REPO_ROOT / args.root
    cards = args.cards if args.cards.is_absolute() else REPO_ROOT / args.cards
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    data = build_data(root, cards)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_document(data), encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Theorems: {len(data['theorems'])}; C-success: {data['c_success_count']}")


if __name__ == "__main__":
    main()
