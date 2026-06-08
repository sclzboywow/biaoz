# Baidu Pan File Storage Design

## Goals

- Keep each Baidu Pan directory below 2000 direct children.
- Make the file library easy to verify, deduplicate, migrate, and clean.
- Avoid coupling crawler speed to remote upload speed.
- Keep the database as the authoritative index.

## Directory Layout

```text
/apps/standard-docs/
  objects/
    sha256/
      ab/
        cd/
          <sha256>.pdf
  manifests/
    yyyy/
      mm/
        <document_version_id>.json
  staging/
    yyyy/
      mm/
        dd/
          <task_id>.part
  failed/
    yyyy/
      mm/
        dd/
          <task_id>.json
```

## File Placement

Official archived files are content-addressed:

```text
objects/sha256/<sha256[0:2]>/<sha256[2:4]>/<sha256><extension>
```

This gives 65,536 second-level buckets. At one million PDFs, the average leaf directory is about 15 files, well below the 2000-file limit.

Every level is bounded:

- `/apps/standard-docs` has a small fixed set of maintenance directories.
- `objects/sha256` has at most 256 first-level hash buckets.
- Each first-level hash bucket has at most 256 second-level hash buckets.
- Each leaf object bucket is monitored and should stay below 2000 files.
- `manifests`, `staging`, and `failed` use `yyyy/mm/dd` partitioning, so year directories have at most 12 children and month directories have at most 31 children.

The original standard number, title, source URL, SPC detail URL, category, and version metadata remain in the database. The remote object path is intentionally stable and short.

## Database Path

`DocumentVersion.file_path` stores:

```text
baidupan:/apps/standard-docs/objects/sha256/ab/cd/<sha256>.pdf#fs_id=<fs_id>
```

The `sha256` remains in `DocumentVersion.file_hash` and `content_hash`.

## Deduplication

The upload key is the SHA-256 of the file bytes. If multiple standards or sources produce the same PDF, they can point to the same object. The database keeps separate logical versions while the remote file is stored once.

## Async Upload Flow

The crawler should not wait on slow remote storage:

1. Capture or download the PDF.
2. Compute `sha256`.
3. Create or update the logical `DocumentVersion`.
4. Enqueue an upload job with `sha256`, filename, size, source id, and local/temp path or byte source.
5. Worker uploads to `objects` with Baidu Pan `content-md5` and `slice-md5`, pulls remote metadata, confirms `fs_id`/path/size, then backfills `file_path`.
6. Failed jobs write diagnostics to `failed/yyyyMMdd/`.

Until the async worker is enabled, `storage_backend=local` remains the default. `baidu_pan` or `dual` should only be enabled after upload queue validation.

## Maintenance

Routine checks:

- Bucket size scan: list `objects/sha256/*/*` and alert if any leaf directory exceeds 1500 files.
- Orphan scan: remote objects not referenced by any `DocumentVersion.file_path`.
- Missing scan: current document versions whose remote object is missing.
- Fast upload verification: send local MD5 in Baidu Pan `content-md5`, then confirm remote `fs_id`/path/size. Baidu Pan `filemetas.md5` is recorded, but it is not treated as a content MD5 because observed values are not normal 32-hex file hashes.
- Hash audit: sample download remote objects and compare SHA-256.
- Failed queue review: inspect `failed/yyyyMMdd/*.json`.

Deletion policy:

- Never delete by filename.
- Delete by object hash only after no database version references the object.
- Prefer moving suspicious objects to `failed` or a quarantine prefix before permanent deletion.
