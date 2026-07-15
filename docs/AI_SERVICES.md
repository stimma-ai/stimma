# LLM Providers

Settings → LLM Providers manages every LLM route available to chats and quick tasks.

## Services and models

A service is a provider account or one local LLM server. OpenAI, Anthropic, xAI,
OpenRouter, and each local server are separate services. Every service owns a
selected model list; two local machines therefore remain independently testable
and removable.

OpenAI, Anthropic, and xAI use checked-in model contracts. OpenRouter and local
servers discover IDs from `GET /models`, but Stimma does not infer reasoning
behavior from a model name. Their model settings expose context, tool support,
reasoning mode and wire control, and an extra request body for manual overrides.

Provider records live in `config.yaml`. Removing one is a soft delete
(`deleted_at`), so saved chats retain an identifiable unavailable route instead
of silently changing models. API keys are masked in API responses.

## Selection rules

- A chat stores a provider-qualified model ID. Existing chats keep it.
- Selecting a model in any chat or new-chat composer makes it the starting model
  for later chats.
- Reasoning is stored per model. If a provider removes a saved level, the model's
  declared default is used.
- Quick tasks have one setting and always use the model's minimum reasoning level.
- A user-owned route wins when it duplicates a Stimma Cloud model. The Stimma
  route remains available under “Also via Stimma Cloud.”
- An unavailable route never falls through to another model.

MiniMax M3 is the initial cloud default. The current Fireworks route is text-only;
the composer asks the user to choose an image-capable model before sending an
attachment.

## Checks and failures

Adding or changing a service validates its `/models` endpoint. A local LLM test
also exercises text, reasoning controls, tools, images, and configured context,
then stores the detected capabilities per model.

The app distinguishes invalid keys, insufficient provider funds, missing models,
access denial, rate limits, Stimma balance, and connection failures. A provider
key's balance usually cannot be known before an inference request; when that
request fails, the chat keeps the message and route visible so the user can fix
the service or choose another model.

## Live certification

The sibling `stimma-evals` repository owns budget-capped provider contracts and
live certification. The lane verifies model discovery, every advertised
reasoning value, tool calls, tool-result continuation, streaming, usage, model
identity, and advertised image input. Use `tools/stimma-evals certify`; API keys
may be loaded from an ignored dotenv/dev-vars file and certificates are ignored.
