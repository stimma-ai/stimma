"""Prompt programs: Enhance prepares a small program from the prompt once; every
generation runs it (no LLM) to get a finished prompt, LoRAs and parameter values.

runtime      the restricted language and its sandbox, the draw API, and discovery of choices.
draws        phased draws for programs whose picks carry specs (about/phase/seed/cls);
             programs without them run through runtime.run().
options      generated options for those picks: the on-disk pools and the background filler.
fluent       what a draw is made from: the options service for a program, replays of a revision.
vocab        curated lists a pick binds to with cls=; narrow narrows them to the prompt.
fix          the fix pass: a small ONNX judge checks each finished draw and rerolls flagged picks.
judge        the Fluent settings (config.yaml `fluent:`).
prepare      the LLM calls that write a program from a prompt, and realize().
session      the writer's session log; instructions.md is what the writer is taught.
store        on-disk cache of prepared programs keyed by their inputs.
"""
