#!/usr/bin/env python3
"""
Generate all possible equation pairs with oracle relationship labels.

This script creates a comprehensive CSV file containing all 4694*4694 = 22,033,636 pairs
of equations from the ETP catalogue, with their semantic relationships determined by
the oracle (equivalent, stronger, weaker, incomparable, or unknown).

Output format matches oracle_labeled_pairs.csv:
    node_a,node_b,relation

Usage:
    python3 generate_oracle_pairs_v2.py [--output OUTPUT_FILE] [--batch-size BATCH_SIZE]

Options:
    --output: Output CSV file path (default: data/oracle_labeled_pairs_v2.csv)
    --batch-size: Number of pairs to process before writing checkpoint (default: 100000)
    --resume: Resume from existing partial output file
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path

# Add oracle directory to path
SCRIPT_DIR = Path(__file__).resolve().parent
ORACLE_DIR = SCRIPT_DIR / "oracle"
sys.path.insert(0, str(ORACLE_DIR))

from oracle import SemanticOracle


def load_equation_index(index_file):
    """Load equation node IDs from the index file.

    The file format is one equation per line, with node ID = line number (1-indexed).

    Returns:
        list: List of equation node IDs (integers)
    """
    nodes = []
    with open(index_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            # Node ID is the line number (1-indexed)
            nodes.append(line_num)
    return sorted(nodes)


def generate_all_pairs(nodes, no_reverse=False):
    """Generate all possible pairs.

    Args:
        nodes: List of equation node IDs
        no_reverse: If True, only generate A→B where A <= B (no reverse pairs)

    Yields:
        tuple: (node_a, node_b) pairs
    """
    if no_reverse:
        # Only generate A→B where A <= B
        for i, node_a in enumerate(nodes):
            for node_b in nodes[i:]:
                yield (node_a, node_b)
    else:
        # Generate all combinations (both directions)
        for node_a in nodes:
            for node_b in nodes:
                yield (node_a, node_b)


def count_existing_pairs(output_file):
    """Count how many pairs are already in the output file.

    Returns:
        int: Number of pairs already processed (excluding header)
    """
    if not os.path.exists(output_file):
        return 0

    with open(output_file, 'r', encoding='utf-8') as f:
        # Count lines, subtract 1 for header
        return sum(1 for _ in f) - 1


def main():
    parser = argparse.ArgumentParser(
        description='Generate all equation pairs with oracle labels'
    )
    parser.add_argument(
        '--output',
        default='data/oracle_labeled_pairs_v2.csv',
        help='Output CSV file path'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100000,
        help='Batch size for progress updates and checkpoints'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from existing partial output file'
    )
    parser.add_argument(
        '--index-file',
        default='etp-semantic-equivalence-repo-natural-latents (2)/data/etp_equations_index.txt',
        help='Path to equations index file'
    )
    parser.add_argument(
        '--sample-equations',
        type=int,
        help='Use only N randomly sampled equations (reduces pairs to N*N)'
    )
    parser.add_argument(
        '--sample-pairs',
        type=int,
        help='Randomly sample N pairs total (fastest option)'
    )
    parser.add_argument(
        '--no-reverse',
        action='store_true',
        help='Only generate A→B, not B→A (cuts pairs in half)'
    )
    parser.add_argument(
        '--first-n',
        type=int,
        help='Use only first N equations from catalogue (deterministic subset)'
    )

    args = parser.parse_args()

    # Resolve paths
    output_file = Path(args.output)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    index_file = SCRIPT_DIR / args.index_file
    if not index_file.exists():
        print(f"Error: Index file not found: {index_file}")
        return 1

    # Load oracle
    print("Loading oracle...")
    oracle = SemanticOracle()

    # Load equation nodes
    print(f"Loading equation index from {index_file}...")
    all_nodes = load_equation_index(index_file)
    print(f"Found {len(all_nodes)} equations in catalogue")

    # Apply equation sampling if requested
    if args.first_n:
        nodes = all_nodes[:args.first_n]
        print(f"Using first {len(nodes)} equations")
    elif args.sample_equations:
        import random
        random.seed(42)
        nodes = sorted(random.sample(all_nodes, min(args.sample_equations, len(all_nodes))))
        print(f"Randomly sampled {len(nodes)} equations")
    else:
        nodes = all_nodes

    n_nodes = len(nodes)

    # Calculate total pairs
    if args.no_reverse:
        # Only A→B where A <= B
        total_pairs = n_nodes * (n_nodes + 1) // 2
        print(f"Will generate {total_pairs:,} pairs (no reverse pairs)")
    else:
        total_pairs = n_nodes * n_nodes
        print(f"Will generate {total_pairs:,} pairs (including both directions)")

    # Apply pair sampling if requested
    if args.sample_pairs and args.sample_pairs < total_pairs:
        print(f"Will randomly sample {args.sample_pairs:,} pairs from {total_pairs:,} possible")

    # Check for resume
    start_idx = 0
    if args.resume and output_file.exists():
        existing = count_existing_pairs(output_file)
        start_idx = existing
        print(f"Resuming from pair {start_idx:,} ({100*start_idx/total_pairs:.2f}%)")
        mode = 'a'
        write_header = False
    else:
        mode = 'w'
        write_header = True

    # Open output file
    print(f"Writing to {output_file}...")

    start_time = time.time()
    processed = 0

    with open(output_file, mode, newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        # Write header if starting fresh
        if write_header:
            writer.writerow(['node_a', 'node_b', 'relation'])

        # Generate pairs (with optional sampling)
        if args.sample_pairs and args.sample_pairs < total_pairs:
            # Random sampling mode
            import random
            random.seed(42)

            # Generate all possible pair indices
            all_pair_indices = list(range(total_pairs))
            sampled_indices = set(random.sample(all_pair_indices, args.sample_pairs))

            pair_generator = generate_all_pairs(nodes, args.no_reverse)
            target_count = args.sample_pairs
        else:
            # Full generation mode
            pair_generator = generate_all_pairs(nodes, args.no_reverse)
            sampled_indices = None
            target_count = total_pairs

        # Generate and label pairs
        for idx, (node_a, node_b) in enumerate(pair_generator):
            # Skip if resuming
            if idx < start_idx:
                continue

            # Skip if not in sampled set (when sampling)
            if sampled_indices is not None and idx not in sampled_indices:
                continue

            # Query oracle for relationship
            verdict = oracle.compare(node_a, node_b)
            relation = verdict.label

            # Write row
            writer.writerow([node_a, node_b, relation])
            processed += 1

            # Progress update
            if processed % args.batch_size == 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed
                remaining = (target_count - start_idx - processed) / rate if rate > 0 else 0
                pct = 100 * (start_idx + processed) / target_count

                print(f"Processed {start_idx + processed:,}/{target_count:,} pairs "
                      f"({pct:.2f}%) | Rate: {rate:.1f} pairs/sec | "
                      f"ETA: {remaining/3600:.1f} hours")

                # Flush to ensure data is written
                f.flush()

            # Stop if we've reached target (for sampling mode)
            if sampled_indices is None and processed + start_idx >= target_count:
                break

    # Final stats
    elapsed = time.time() - start_time
    print(f"\nCompleted! Processed {processed:,} pairs in {elapsed/3600:.2f} hours")
    print(f"Average rate: {processed/elapsed:.1f} pairs/sec")
    print(f"Output written to: {output_file}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
