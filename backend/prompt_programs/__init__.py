"""Prompt programs: Enhance prepares a small program from the prompt once; every
generation runs it (no LLM) to get a finished prompt, LoRAs and parameter values.

runtime  — the restricted language, the draw API, and discovery of choices.
draws    — phased, judged draws for programs whose picks carry specs (about/phase/seed);
           programs without them keep running through runtime.run().
prepare  — the LLM call that writes a program from a prompt.
store    — on-disk cache of prepared programs keyed by their inputs.
"""
