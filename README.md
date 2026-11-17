# file-station

Personal file transfer station powered by [updog](https://github.com/sc0tfree/updog), deployed on Abasthan.

- Browse, upload and download files through the web UI.
- Protected by HTTP Basic Auth (empty username + password from the `FILE_PASSWORD` environment variable).
- Uploaded files live in `files/` (git-ignored).
