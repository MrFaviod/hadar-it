# Asset attachments

Attachments store metadata in `asset_attachments` and bytes outside the main SQL
DB through `BlobStorage`. The default local adapter uses opaque keys under
`ITSM_ATTACHMENT_STORAGE_PATH` (default `/data/attachments`). Mount a persistent
volume there for both API and worker processes; root Compose integration follows
in Phase 6. No external storage provider is required. Existing photo/fov image
endpoints retain their independent 1 MiB SQL-backed contract.

## HTTP

- `GET /api/v1/assets/{asset_id}/attachments?limit=50&offset=0`: bounded metadata,
  with `hasMore`. Requires `assets.view`.
- `POST /api/v1/assets/{asset_id}/attachments?filename=receipt.pdf&category=receipt`:
  raw binary body; returns metadata and a download URL (201). Requires
  `assets.edit`, cookie Origin/CSRF or authenticated machine bearer.
- `GET /api/v1/assets/{asset_id}/attachments/{id}/download`: authorized download,
  attachment disposition, no-store and nosniff. Requires `assets.view`.
- `DELETE /api/v1/assets/{asset_id}/attachments/{id}`: 204. Requires `assets.edit`.

Categories: `photo`, `receipt`, `manual`, `document`. Upload limit defaults to
10 MiB; `ITSM_ATTACHMENT_MAX_BYTES` accepts 1 byte through 50 MiB. Filename is a
bounded display label, never a filesystem key. Traversal and control characters
are rejected. Content type comes from the validated content/extension, not the
request's declaration. Raster images, PDF and UTF-8 text/CSV are supported.
Active HTML/SVG and executables are not accepted. PDF/raster checks identify file
formats, not malware scanning or full document integrity; downloads are never
rendered inline by this API. No OCR or document interpretation is performed.

## Failure and lifecycle semantics

Uploads authorize and validate before touching storage. A complete durable blob
is written before committing metadata/history; ordinary SQL failure removes the
new blob. An abrupt process crash between blob write and SQL commit can leave an
unreferenced blob; it does not create a downloadable SQL record. No automatic
orphan deletion is implemented.

Deletion first commits an inaccessible tombstone and history, then removes the
blob and metadata. Storage failure returns 503; the original DELETE can retry
cleanup without another history event. Downloads and lists exclude tombstones.
A crash may leave hidden bytes for this controlled retry. Permanent asset purge
refuses remaining attachment rows, including cleanup-pending tombstones; deletion
must complete first. Archive retains documents. SQL backups alone do not back up
file bytes: retain the volume and metadata together.

Local operations use directory file descriptors and `O_NOFOLLOW` on every path
component and opaque key. Storage failures disclose no paths. Missing/corrupted
blobs return 503, not fabricated content. Future adapters implement the same
bounded put/read/delete interface without changing business services.

## Chat attachments

Chat attachments are a separate, owner-scoped family stored on the same
independent blob store (`attachment_storage_path`) and created from
`itsm/agent_integrations/attachments.py`. They reuse `validate_chat_attachment`,
which applies the same signature sniffing as asset documents: raster PNG, JPEG,
WebP and GIF only when the bytes and the extension agree, PDF (`%PDF-` plus
`%%EOF`), and UTF-8 `.txt`/`.csv`. HTML, SVG, executables, empty bodies and
mismatched pairs are `422 validation_error`.

They are not inventory records: no asset history entry, no asset download URL
and no warranty or intervention reference points at them. The table
(`agent_chat_attachments`, migration `0034_chat_attachments`) stores the blob
key, media type, kind, size, SHA-256 and the owning session/owner, and bytes are
read back with a size and digest check before a turn uses them. For asset
attachments used in a chat turn, `read_for_chat` keeps the ordinary authority:
`assets.view` on the asset that owns the attachment, with `404 not_found` for
missing, deleted or foreign records.

Lifecycle: an upload belongs to one session and one owner; deleting the
attachment or the session deletes the row and the blob, and a failed upload or a
failed write removes the freshly stored blob. Bounds are 4 attachments and 4 MiB
of decoded bytes per message, 4 MiB per chat attachment (or
`attachment_max_bytes` when smaller) and 20 stored chat attachments per session.
