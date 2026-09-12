"""Forkcast deterministic scoring engine (forkcast-proposal.md §5).

The LLM never ranks anything here: every function in this package takes a validated
`ConceptProfile` plus in-memory NumPy/pandas feature frames and returns plain numbers.
`engine.analyze()` is the public entry point other agents import.
"""
