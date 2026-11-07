"""Prompt programs: Enhance prepares a small program from the prompt once; every
generation runs it (no LLM) to get a finished prompt, LoRAs and parameter values.

runtime  — the restricted language, the draw API, and discovery of choices.
prepare  — the LLM call that writes a program from a prompt.
store    — on-disk cache of prepared programs keyed by their inputs.
"""
