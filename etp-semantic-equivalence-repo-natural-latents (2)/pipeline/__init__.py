"""
pipeline -- one evaluation harness for every equation-relation method.

Every method (symmetric baselines, Natural Latents losses, advanced metrics,
structural / WL features, threshold rules, magma semantics) is evaluated on
the SAME sampled equations, the SAME labelled pairs, the SAME node-held-out
splits and -- when it learns anything -- the SAME base classifier. Results
(confusion matrices, per-class precision / recall / specificity / F1 /
accuracy, and macro scores) are written to one Excel sheet.

Entry point:  python run_all.py --help   (in the folder above this package)

The low-level algorithms live in ../src (unchanged, still used by the
notebooks); this package only wires them together.
"""
