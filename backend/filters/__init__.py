"""Built-in image filters — first-class app capabilities.

Definitions mirror the editor (packages/image-editor/src/filterDefs.ts);
the ops are NumPy/PIL ports of the editor's pixel math. They are exposed as
tools on the built-in lightweight provider (task type "filter"), so the
chat agent, flows, and post-processing chains all invoke them through the
normal tool path.
"""
