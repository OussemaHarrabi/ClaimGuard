"""Rulebook edge-case suite for the ``claimguard.edu`` engine.

The public gold splits do not discriminate several rulebook edges, so an
implementation could be wrong exactly there and still score 1.0 on every supplied
label. These tests pin the *stated* semantics of the pack rulebook instead of the
sampled behaviour; ``test_rulebook_edges.py`` carries the cases and the clause
citations.
"""
