"""Fluent: the parts of a prompt the user marked to vary (<young man>, {a|b}), read and drawn.

slots          the grammar, the parse, and a prompt's entry now: instant, read in the background.
reader         the model call that says what one slot is.
seeding        the lists a slot's variants are seeded from, narrowed by its words.
narrow         a list narrowed to what a slot's words allow.
variants       the writer: a slot's variants of the user's words, checked.
variant_pools  the pools on disk, least-used drawing, writes in the background.
fill           one image's text, drawn from the pools and the user's lists.
fluent         what realize() draws with, what a picker shows, counting shipped draws.
vocab          curated lists that seed the writer.
choices        what the user chose in the chooser.
fix            the judge pass on each finished draw, and rerolls of what it refuses.
judge          the Fluent settings (config.yaml `fluent:`).
program        masking, the store, the chat model, realize().
store          on-disk entries keyed by their inputs.
"""
