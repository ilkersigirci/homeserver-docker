# Open WebUI

Thin wrapper over the pinned official Open WebUI slim image. Its patches let an
Open WebUI that signs users in with OIDC send each user's own OAuth token where
upstream allows only a shared key, let a Pipe describe the models it lists, let
a connection leave out models by pattern, and can keep chat uploads raw for an
external Files API.

## Image contents

Each patch's header records the upstream gap, any upstream reports, what the
patch changes, and its removal check.

- [`pipes-user-context.patch`](patches/pipes-user-context.patch): a manifold
  Pipe's `pipes()` receives the user's OAuth token when it declares
  `__oauth_token__`, as `pipe()` does, so a Pipe can list each user's models
  with that user's credential.
- [`pipes-model-info.patch`](patches/pipes-model-info.patch): each `pipes()`
  entry may carry an `info` dict, which becomes the listed model's info, as a
  stored model record would provide it: description, capabilities, default
  tools, Filters, and Chat Variables form. A stored record still replaces it.
  Upstream declined this ([open-webui#23047](https://github.com/open-webui/open-webui/issues/23047)).
- [`openai-exclude-model-ids.patch`](patches/openai-exclude-model-ids.patch):
  an OpenAI connection's `exclude_model_ids` in `OPENAI_API_CONFIGS` holds glob
  patterns, such as `acme/*`, matched against the provider's model IDs. Each
  time Open WebUI lists models, the matching ones are left out of that
  connection, so a deployment can hide a model family, such as the models a
  Pipe already serves, while new provider models still appear, without stored
  model records or a `model_ids` allowlist.
- [`speech-images-system-oauth.patch`](patches/speech-images-system-oauth.patch):
  speech-to-text, text-to-speech (the `openai` and `openai-realtime` engines),
  realtime voice calls, image generation, and image editing authenticate like
  the OpenAI connection with the same base URL. When that connection's
  `auth_type` is `system_oauth`, they send the user's OAuth token instead of
  their configured key; otherwise they keep the key. Only the auth type is
  shared; the connection's custom headers still apply to chat only.
- [`file-upload-processing.patch`](patches/file-upload-processing.patch), a
  temporary upstream workaround: `ENABLE_FILE_UPLOAD_PROCESSING=false` stores
  chat uploads without extraction or embedding, for deployments whose Pipes
  send files to an external Files API. Unset, uploads are processed as
  upstream does.

A user without an OAuth session gets no token, never a fallback to a shared
key. [`tests/`](tests/) checks every patch against the patched modules on
every build.

## Updating

`IMAGE_VERSION` selects the official tag and the published tag. The build
applies every patch under `patches/` with zero fuzz and runs `tests/`, so an
upstream change near a patch stops the build for review.

At each Open WebUI upgrade, check each patch's removal condition first. Rebase
a patch that no longer applies by editing the upstream files from the new image
and regenerating the diff. Remove a patch, its test, and its entry above once
an official release provides the behavior.
