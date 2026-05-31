# ADR-004: Model Versioning Strategy

**Status:** Accepted
**Date:** 2026-05-31

## Context

The `ForgeModel` row is mutable (authors edit name, schema, prompt, tool classes in drafts).
`ModelVersion` is the immutable history store. The question: when is a `ModelVersion` row written?

## Decision: Version at publish time

Draft edits mutate the `models` row in place (`current_version` is unchanged during draft edits).
When `POST /api/models/{id}/publish` is called, the current config is snapshotted into a new
`ModelVersion` row and `current_version` is incremented atomically.

The transaction at publish time: `INSERT model_versions` + `models.current_version++` +
`models.status = "published"` — all in one `db.commit()`.

**Why:** Publishing is the semantically meaningful checkpoint — it's when a config becomes
"live" and starts serving MCP clients. Versioning at edit time would create version proliferation
with no semantic boundary. This also mirrors the Phase 4 snapshot-copy pattern.

## Implications

- `current_version = 0` on a fresh draft (no version row exists yet).
- After first publish: `current_version = 1` and `model_versions` has one row.
- Re-publish after edit: version 2 is written, containing the edited config.
- `GET /api/models/{id}/versions` surfaces the entire published history.

## Slug / id generation

The model `id` is the slug PK, generated at draft-create time from the name:
lowercase → strip non-alphanum → collapse whitespace/dashes → truncate to 128 chars.
Collision detection (if slug exists, append `-{uuid4[:8]}`).

## State transitions

```
draft → published    (via /publish — validates schema, creates version)
published → unpublished  (via /unpublish)
unpublished → published  (via /publish again — creates another version)
draft → unpublished  (rejected — 409)
published → draft    (not implemented — unpublish first, then edit in unpublished state)
```

Published models cannot be edited via PATCH — unpublish first.
This keeps the gateway invariant clean: the gateway always reads the row, and
`status == "published"` is the only gate it checks.
