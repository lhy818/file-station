# file-station

Personal file transfer station, deployed on Abasthan.

- Web UI: browse, upload, download, delete.
- Protected by HTTP Basic Auth: **empty username** + password from the
  `FILE_PASSWORD` environment variable.
- Uploaded files live in `files/` (git-ignored).

## Why chunked uploads

The hosting ingress (nginx) caps a single request body at ~1 MB
(verified 2026-11-17: 500 KB uploads pass, 1 MB uploads get HTTP 413).
The web UI therefore splits every file into 768 KB chunks and uploads
them sequentially to `POST /chunk`; the server reassembles the file
once all chunks arrive. Downloads have no such cap.

## Chunk upload protocol

`POST /chunk`, multipart form fields:

| field      | meaning                              |
|------------|--------------------------------------|
| `chunk`    | one file chunk (<= 768 KB recommended) |
| `upload_id`| random id for this upload (alphanumeric, `-_`) |
| `index`    | 0-based chunk index                  |
| `total`    | total number of chunks               |
| `filename` | original file name                   |

Chunks may be retried individually (same index overwrites the same part
file). When the part count equals `total`, the server concatenates the
parts in index order into `files/<filename>`.

Single-request upload (`POST /upload`, field `file`) still exists for
small files under the ~1 MB ingress cap.

## curl example (chunked upload of a large file)

```bash
U=https://<your-app>.abasthan.app
PW='<password>'
F=bigfile.bin
ID=$(date +%s)$RANDOM
SZ=$(stat -c%s "$F"); CH=786432; TOTAL=$(( (SZ + CH - 1) / CH ))
split -b $CH -d "$F" /tmp/part_
i=0
for p in /tmp/part_*; do
  curl -s -H 'Expect:' -u ":$PW" \
    -F "chunk=@$p" -F "upload_id=$ID" -F "index=$i" -F "total=$TOTAL" \
    -F "filename=$(basename "$F")" "$U/chunk" >/dev/null
  i=$((i+1))
done
rm -f /tmp/part_*
```

Note: `Expect:` (empty) matters — curl sends `Expect: 100-continue` for
multipart bodies, which the Cloudflare edge in front of the app rejects
with HTTP 413 even for small uploads.
