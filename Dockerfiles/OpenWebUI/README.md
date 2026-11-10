# Open WebUI

Thin wrapper over the pinned official Open WebUI slim image. Its patches let an
Open WebUI that signs users in with OIDC send each user's own OAuth token where
upstream allows only a shared key, let a Pipe describe the models it lists, let
a connection leave out models by pattern, and let chat documents go through an
OpenAI-compatible Files API.

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
- [`openai-files-api.patch`](patches/openai-files-api.patch): chat documents
  use an OpenAI-compatible Files API, such as one behind LiteLLM's
  `files_settings`. Models that read files by ID receive them by ID, and the
  Files API can extract every document's text; see [Files API](#files-api).
  Upstream closed both native file input PRs unmerged
  ([open-webui#27627](https://github.com/open-webui/open-webui/pull/27627),
  [open-webui#27998](https://github.com/open-webui/open-webui/pull/27998)).

A user without an OAuth session gets no token, never a fallback to a shared
key. [`tests/`](tests/) checks every patch against the patched modules on
every build.

## Files API

| Variable | Meaning |
| --- | --- |
| `ENABLE_OPENAI_FILES_API` | `true` turns the integration on; default `false`. |
| `OPENAI_FILES_API_BASE_URL` | Files API base URL, including `/v1`. |
| `OPENAI_FILES_API_KEY` | Key used unless the OpenAI connection with the same base URL uses `system_oauth`. |
| `OPENAI_FILES_API_PARAMS` | JSON object of string query parameters for every Files API request, such as `{"provider":"litellm_proxy"}` to select LiteLLM's `files_settings` entry. |
| `OPENAI_FILES_API_MODELS_REGEX_PATTERN` | Model IDs that receive documents by file ID, such as `^langflow/`; a workspace model matches by its base model. Empty or invalid sends none. |
| `OPENAI_FILES_API_TIMEOUT` | Seconds each Files API request may take, text extraction included; default `300`. |
| `CONTENT_EXTRACTION_ENGINE` | `openai_files` extracts each processed upload's text through the Files API. |

### Sending files by ID

Open WebUI uploads a file the first time it needs one, with
`purpose=user_data`, and keeps the returned ID in the file's metadata. In a
saved chat, each user message sent to a matching model carries its documents
as standard Chat `file` parts with that ID. A connection with
`"api_type": "responses"` sends them as `input_file`, and so does LiteLLM for a
deployment with `model_info.mode: responses`, such as a Langflow flow. Open
WebUI's retrieval and file tools leave those documents out.

Open WebUI handles the rest as usual: images, audio, and video; files the user
cannot read; documents whose upload fails, which it logs; and temporary chats,
whose messages carry no files. A file has one ID, sent for every user who can
read the file, so the Files API must accept any user's request for it, as
LiteLLM's `files_settings` backend does. Open WebUI never checks an ID again,
so the Files API must keep its files.

### Extracting text

With the `openai_files` engine, processing an upload sends
`GET /files/{file_id}/content?format=markdown` and stores a `text/markdown` or
`text/plain` response, read as UTF-8 unless it names a charset, as the
document's text. Without `format`, the Files API returns the original bytes, as
OpenAI's does. Any other response fails the processing; Open WebUI shows the
error and keeps the file attached, so models that read files by ID still
receive it.

Documents Open WebUI downloads from the web, such as PDFs in search results,
have no upload, so the built-in loaders read them; in the slim image those read
only text, HTML, and CSV. The admin **Documents** page lists no such engine, and
saving that page writes its engine value over `CONTENT_EXTRACTION_ENGINE`; after
saving it, check that `GET /api/v1/retrieval/config` still reports
`openai_files`.

Requests authenticate like the OpenAI connection with the same base URL, as in
`speech-images-system-oauth.patch`. Open WebUI never deletes files from the
Files API.

## Updating

`IMAGE_VERSION` selects the official tag and the published tag. The build
applies every patch under `patches/` with zero fuzz and runs `tests/`, so an
upstream change near a patch stops the build for review.

At each Open WebUI upgrade, check each patch's removal condition first. Rebase
a patch that no longer applies by editing the upstream files from the new image
and regenerating the diff. Remove a patch, its test, and its entry above once
an official release provides the behavior.
