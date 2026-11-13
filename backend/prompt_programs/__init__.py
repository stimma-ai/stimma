"""Fluent: the parts of a prompt the user marked to vary (<young man>, {a|b}), read and drawn.

slots        the grammar, the parse, and a prompt's entry now: instant, read in the background.
reader       the model call that says what one slot is.
fill         a slot's picks from its reading, and one image's text drawn segment by segment.
options      written options for the picks: the on-disk pools and the background filler.
fluent       the options service a draw reads, replays of a revision, what a picker shows.
vocab        curated lists a pick binds to; narrow narrows them by the slot's words.
choices      what the user chose in the chooser, as pins, edits and zones.
fix          the judge pass on each finished draw, and rerolls of what it refuses.
judge        the Fluent settings (config.yaml `fluent:`).
program      masking, the store, the chat model, realize().
store        on-disk entries keyed by their inputs.
"""
