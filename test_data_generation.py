#!/usr/bin/env python3
"""
Test script to validate data generation setup before running full generation.

This script performs quick checks to ensure:
1. Index file is accessible
2. Oracle can be loaded (if built)
3. Translation files can be found
4. Output directories are writable

Run this before starting the long-running full generation.
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def test_index_file():
    """Test that equation index file exists and is readable."""
    print("=" * 60)
    print("TEST 1: Equation Index File")
    print("=" * 60)

    index_file = SCRIPT_DIR / "etp-semantic-equivalence-repo-natural-latents (2)" / "data" / "etp_equations_index.txt"

    if not index_file.exists():
        print(f"❌ FAIL: Index file not found at {index_file}")
        return False

    try:
        with open(index_file, 'r') as f:
            lines = [line for line in f if line.strip()]
            print(f"✓ Index file found: {index_file}")
            print(f"✓ Contains {len(lines)} equations")
            print(f"✓ First equation: {lines[0].strip()}")
            print(f"✓ Last equation: {lines[-1].strip()}")
        return True
    except Exception as e:
        print(f"❌ FAIL: Could not read index file: {e}")
        return False


def test_oracle():
    """Test that oracle can be loaded."""
    print("\n" + "=" * 60)
    print("TEST 2: Oracle Setup")
    print("=" * 60)

    oracle_dir = SCRIPT_DIR / "oracle"
    sys.path.insert(0, str(oracle_dir))

    matrix_file = oracle_dir / "data" / "matrix.bin"
    meta_file = oracle_dir / "data" / "matrix_meta.json"

    if not matrix_file.exists():
        print(f"⚠ WARNING: Oracle matrix not built yet")
        print(f"  Expected: {matrix_file}")
        print(f"  Run: cd oracle && python3 build_matrix.py")
        print(f"  This is REQUIRED for generate_oracle_pairs_v2.py")
        return False

    try:
        from oracle import SemanticOracle
        oracle = SemanticOracle()
        print(f"✓ Oracle loaded successfully")
        print(f"✓ Matrix file: {matrix_file}")
        print(f"✓ Matrix size: {oracle.n}x{oracle.n} = {oracle.n * oracle.n:,} entries")

        # Test a simple query
        verdict = oracle.compare(1, 1)
        print(f"✓ Test query: Eq1 vs Eq1 → {verdict.label}")
        return True

    except Exception as e:
        print(f"❌ FAIL: Could not load oracle: {e}")
        return False


def test_translation_files():
    """Test that translation files can be found."""
    print("\n" + "=" * 60)
    print("TEST 3: Translation Files")
    print("=" * 60)

    translate_dir = SCRIPT_DIR / "translate"

    if not translate_dir.exists():
        print(f"❌ FAIL: Translate directory not found: {translate_dir}")
        return False

    print(f"✓ Translate directory: {translate_dir}")

    # Check for key translation files
    translations = {
        'lean': 'lean/etp_equations_lean.json',
        'latex': 'latex/etp_equations_latex.json',
        'py_lambda': 'py_lambda/etp_equations_py_lambda.json',
        'natural_language': 'nl/etp_equations_nl.json',
    }

    found_count = 0
    for name, path in translations.items():
        file_path = translate_dir / path
        if file_path.exists():
            size_mb = file_path.stat().st_size / (1024 * 1024)
            print(f"  ✓ {name:20s}: {size_mb:.1f} MB")
            found_count += 1
        else:
            print(f"  ✗ {name:20s}: not found")

    if found_count == 0:
        print(f"❌ FAIL: No translation files found")
        return False

    print(f"\n✓ Found {found_count}/{len(translations)} core translation files")
    return True


def test_output_directories():
    """Test that output directories exist and are writable."""
    print("\n" + "=" * 60)
    print("TEST 4: Output Directories")
    print("=" * 60)

    data_dir = SCRIPT_DIR / "etp-semantic-equivalence-repo-natural-latents (2)" / "data"

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"✓ Data directory: {data_dir}")

        # Test write permission
        test_file = data_dir / ".test_write"
        test_file.write_text("test")
        test_file.unlink()
        print(f"✓ Directory is writable")
        return True

    except Exception as e:
        print(f"❌ FAIL: Cannot write to output directory: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("DATA GENERATION SETUP VALIDATION")
    print("=" * 60 + "\n")

    results = {
        'index': test_index_file(),
        'oracle': test_oracle(),
        'translations': test_translation_files(),
        'output': test_output_directories(),
    }

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for test, passed in results.items():
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"{test:15s}: {status}")

    print("\n" + "=" * 60)

    if results['index'] and results['translations'] and results['output']:
        print("✓ Ready to run: build_equations_representations_v2.py")
    else:
        print("❌ Fix issues before running build_equations_representations_v2.py")

    if results['oracle']:
        print("✓ Ready to run: generate_oracle_pairs_v2.py")
    else:
        print("⚠ Oracle not built - see oracle/README.md for setup")
        print("  generate_oracle_pairs_v2.py will NOT work until oracle is built")

    print("=" * 60)

    # Return exit code
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
