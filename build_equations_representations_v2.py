#!/usr/bin/env python3
"""
Build equations_representations_v2.json by combining all available translations.

This script reads the ETP equations index and all available representation
translations from the translate/ directory, assembling them into a comprehensive
JSON file with all representations for each equation.

Representations included:
- formal: Original formal notation (from index)
- lean: Lean proof assistant format
- latex: LaTeX mathematical notation
- py_lambda: Python lambda function
- py_cayley_table: Python Cayley table verification
- natural_language: Human-readable prose description
- ssa: Static Single Assignment form
- slots: Positional slot encoding
- rpn: Reverse Polish Notation
- polish: Polish prefix notation
- tptp: TPTP theorem prover format
- smtlib: SMT-LIB format
- ascii_tree: ASCII tree representation
- graphviz: DOT graph format
- json_ast: JSON abstract syntax tree
- confusable_vars: Confusable variable names
- word_problem: Word problem format
- text: Mechanical English with delimiters
- text2: Mechanical English with arity

Usage:
    python3 build_equations_representations_v2.py [--output OUTPUT_FILE]
"""

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
TRANSLATE_DIR = SCRIPT_DIR / "translate"
DATA_DIR = SCRIPT_DIR / "etp-semantic-equivalence-repo-natural-latents (2)" / "data"


# Map of representation names to their JSON files in translate/
REPRESENTATION_FILES = {
    'lean': 'lean/etp_equations_lean.json',
    'latex': 'latex/etp_equations_latex.json',
    'py_lambda': 'py_lambda/etp_equations_py_lambda.json',
    'py_cayley_table': 'py_cayley_table/etp_equations_py_cayley_table.json',
    'natural_language': 'nl/etp_equations_nl.json',
    'ssa': 'ssa/etp_equations_ssa.json',
    'slots': 'slots/etp_equations_slots.json',
    'rpn': 'rpn/etp_equations_rpn.json',
    'polish': 'polish/etp_equations_polish.json',
    'tptp': 'tptp/etp_equations_tptp.json',
    'smtlib': 'smtlib/etp_equations_smtlib.json',
    'ascii_tree': 'ascii_tree/etp_equations_ascii_tree.json',
    'graphviz': 'graphviz/etp_equations_graphviz.json',
    'json_ast': 'json_ast/etp_equations_json_ast.json',
    'confusable_vars': 'confusable_vars/etp_equations_confusable_vars.json',
    'word_problem': 'word_problem/etp_equations_word_problem.json',
    'text': 'text/etp_equations_text.json',
    'text2': 'text2/etp_equations_text2.json',
}


def load_equation_index(index_file):
    """Load formal equations from the index file.

    The file format is one equation per line, with node ID = line number (1-indexed).

    Returns:
        dict: Mapping from node ID (int) to formal equation string
    """
    equations = {}
    with open(index_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            # Node ID is the line number (1-indexed)
            # Line contains just the equation text
            equations[line_num] = line

    return equations


def load_representation(repr_file, repr_key):
    """Load a single representation from its JSON file.

    Args:
        repr_file: Path to the representation JSON file
        repr_key: Key name for the representation in the JSON

    Returns:
        dict: Mapping from node ID (int) to representation string,
              or None if file doesn't exist
    """
    if not repr_file.exists():
        return None

    try:
        with open(repr_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Extract equations list
        if 'equations' in data:
            equations = data['equations']
        else:
            equations = data

        # Build mapping from node to representation
        result = {}
        for eq in equations:
            if isinstance(eq, dict):
                # Try to find node ID
                node = eq.get('node') or eq.get('number') or eq.get('id')
                # Try to find representation value
                value = eq.get(repr_key) or eq.get('text') or eq.get('rendering')

                if node is not None and value is not None:
                    result[int(node)] = value

        return result

    except Exception as e:
        print(f"Warning: Could not load {repr_file}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Build comprehensive equations representations JSON v2'
    )
    parser.add_argument(
        '--output',
        default='etp-semantic-equivalence-repo-natural-latents (2)/data/equations_representations_v2.json',
        help='Output JSON file path'
    )
    parser.add_argument(
        '--index-file',
        default='etp-semantic-equivalence-repo-natural-latents (2)/data/etp_equations_index.txt',
        help='Path to equations index file'
    )
    parser.add_argument(
        '--pretty',
        action='store_true',
        help='Pretty-print JSON output (larger file but readable)'
    )

    args = parser.parse_args()

    # Resolve paths
    output_file = SCRIPT_DIR / args.output
    output_file.parent.mkdir(parents=True, exist_ok=True)

    index_file = SCRIPT_DIR / args.index_file
    if not index_file.exists():
        print(f"Error: Index file not found: {index_file}")
        return 1

    # Load formal equations
    print(f"Loading equation index from {index_file}...")
    formal_equations = load_equation_index(index_file)
    n_equations = len(formal_equations)
    print(f"Found {n_equations} equations")

    # Load all representations
    print(f"\nLoading representations from {TRANSLATE_DIR}...")
    representations = {}

    for repr_name, repr_path in REPRESENTATION_FILES.items():
        repr_file = TRANSLATE_DIR / repr_path

        # Infer the key name from the file basename if not obvious
        repr_key = repr_name

        print(f"  Loading {repr_name}...", end=' ')
        repr_data = load_representation(repr_file, repr_key)

        if repr_data is not None:
            representations[repr_name] = repr_data
            print(f"✓ ({len(repr_data)} equations)")
        else:
            print(f"✗ (file not found or error)")

    print(f"\nLoaded {len(representations)} representations")

    # Build combined data structure
    print("\nCombining all representations...")
    combined = []

    for node in sorted(formal_equations.keys()):
        eq_data = {
            'node': node,
            'formal': formal_equations[node]
        }

        # Add all available representations
        for repr_name, repr_data in representations.items():
            if node in repr_data:
                eq_data[repr_name] = repr_data[node]
            else:
                eq_data[repr_name] = None

        combined.append(eq_data)

    # Write output
    print(f"\nWriting to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        if args.pretty:
            json.dump(combined, f, ensure_ascii=False, indent=2)
        else:
            json.dump(combined, f, ensure_ascii=False)

    # Statistics
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total equations: {len(combined)}")
    print(f"Representations per equation:")

    # Count coverage for each representation
    for repr_name in sorted(representations.keys()):
        count = sum(1 for eq in combined if eq.get(repr_name) is not None)
        pct = 100 * count / len(combined)
        print(f"  {repr_name:20s}: {count:4d} / {len(combined)} ({pct:.1f}%)")

    print(f"\nOutput written to: {output_file}")
    file_size_mb = output_file.stat().st_size / (1024 * 1024)
    print(f"File size: {file_size_mb:.1f} MB")

    return 0


if __name__ == '__main__':
    sys.exit(main())
