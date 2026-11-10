# Guarded chat attachments

The user conversation (`#/conversacion`) can send three kinds of inline input to
the selected engine: chat images, PDF documents and UTF-8 text/CSV, plus
attachments that already exist on the asset that provides the chat context.
There are no remote URLs, provider file ids or browser-side storage of bytes.

## Server contract used by the browser

| Call | Purpose |
| --- | --- |
| `POST /api/v1/agent/sessions/{id}/attachments?filename=…` | Raw bytes upload. Server sniffs PNG/JPEG/WebP/GIF/PDF/UTF-8 text or CSV and returns `201 {id, filename, mediaType, kind: image\|file\|text, size}`. |
| `DELETE /api/v1/agent/sessions/{id}/attachments/{attachmentId}` | Removes a pending session attachment, `204`. |
| `POST /api/v1/agent/sessions/{id}/messages` | Accepts `attachmentIds` (chat uploads) and `assetAttachmentIds` (existing asset attachments). `message` may be empty when attachments are present. |
| `GET /api/v1/agent/sessions/{id}` | Resumed messages may carry `attachments` metadata. |
| `GET /api/v1/assets/{assetId}/attachments?limit=50&offset=0` | Existing asset attachments, requires `assets.view`. |

Uploads reuse `AssetAccess.request`, so the body is an `ArrayBuffer` and the
existing session cookie, Origin and CSRF header apply unchanged. The browser
never sets a content type: the server sniffs the real one.

Server limits, mirrored as an early client guard: 4 MiB per file, 4 MiB decoded
total per message, 4 attachments per message and 20 per session. The per-message
count and byte budget are shared by chat uploads and selected asset attachments,
so selecting an asset attachment is refused when the combined turn would exceed
them. A size the server did not report is treated as unknown, never as zero:
such a row is listed as "Tamaño no informado" and cannot be selected, because the
combined budget cannot be verified. The API stays authoritative; the mirror only
avoids a doomed upload.

## Capability detection and owner marks

Support is never inferred from an engine name, model name or version.

- **Engine gate.** `instances[].attachmentsSupported` must be `true`. A missing
  or false flag hides the attachment control and rejects the attachment path
  (fail closed). This is what separates OpenCode v1 (attachments) from OpenCode
  v2 (not yet supported), Hermes and direct engines without the explicit flag.
- **Model modality.** A Pydantic AI instance model carries
  `inputs: {image: bool|null, file: bool|null}`. Personal managed models use the
  provider `modelCapabilities[id]` marks (`image`, `file`, `source`). Only an
  explicit `true` admits the modality; `null` or absent marks refuse it.
- **Text fallback.** UTF-8 `.txt`/`.csv` is sent as bounded text and only needs
  the engine flag, matching the backend rule.
- The accepted MIME/extension list in the native picker is derived from those
  two answers, and the help text names exactly the formats currently admitted.

Owner capability marks edited in `#/configuracion/…` (provider panel) travel to
the chat through `GET /agent/providers` → `modelCapabilities`; the chat keeps
them in memory only.

## Interaction rules

- The pending list is the authority, not the native input. Removing a row calls
  the server first and drops the row only after a `204`; a failed deletion keeps
  the row and shows the server message.
- Sending an attachment-only message is allowed for chat uploads and for
  selected existing asset attachments; the text remains optional.
- A rejected send (for example `422 engine_attachments_unsupported` or
  `422 model_modality_unsupported`) restores the exact draft and pending rows.
  Nothing is replayed automatically, and the person retries explicitly.
- While attachments are pending the session, engine, profile, provider and model
  selectors are disabled, so a modality answer cannot silently change under a
  pending file. The surface states this instead of failing later.
- Asset attachments are listed only after an explicit load; only ids the server
  returned can be checked, and the asset id must come from the existing
  server-backed chat context.
- `422 model_modality_unsupported` and `422 engine_attachments_unsupported` are
  rendered as factual errors; no fallback engine is chosen on the person's
  behalf.

## Lifecycle and privacy

Bytes and filenames never touch `localStorage`. The transcript stores metadata
only (`id`, safe filename base name, media type, kind, size) and `history()`
keeps sending `{role, content}` only, so a resumed conversation cannot resend an
old attachment. Logout, unmount, identity replacement and a new/resumed session
clear pending rows and abort in-flight uploads; the monotonic epoch check runs
after `file.arrayBuffer()` and after the upload response, so a late upload can
neither revive a signed-out surface nor report a stored file that was discarded.
