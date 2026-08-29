# Source ingestion security boundary

StudyAgent accepts public HTTPS course pages and syllabus uploads in PDF, HTML,
Markdown, or plain text. Uploads are the supported path for CalNet-gated pages;
the service does not automate university SSO.

## Guardrails

- URL fetches reject credentials, non-HTTPS schemes, non-standard ports,
  redirects, and any hostname resolving to a private, loopback, link-local,
  reserved, or otherwise non-public address.
- Downloads and uploads stop at 10 MB. PDFs stop at 200 pages and normalized
  text stops at 500,000 characters.
- Raw and normalized snapshots use deterministic content-addressed object names
  in a private Cloud Storage bucket. Firestore records `uploading`, `ready`, or
  `error` state, so a partial write is visible and retryable.
- The Gemini extractor receives at most 200,000 normalized characters, has no
  tools, makes at most one model call, times out after 30 seconds, and returns
  schema-validated events with source evidence. Invalid output produces zero
  candidates.

## Known limitation

The URL guard resolves and validates DNS before the HTTP client connects, but it
does not pin that result through TLS. A hostile DNS server could theoretically
change its answer between validation and connection. For this single-user
hackathon build, only user-supplied course URLs are accepted; a production
multi-user version should use a network egress proxy that enforces destination
IP policy at connection time.
