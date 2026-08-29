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
- Each logical URL or upload has a stable source ID. Every content change creates
  an immutable revision containing its hash, media type, fetch time, parser
  version, and private raw and normalized Cloud Storage references. Firestore
  records `uploading`, `ready`, or `error` state, so a partial write is visible
  and retryable without overwriting an older revision.
- The Gemini extractor receives at most 200,000 normalized characters, has no
  tools, makes at most one model call, times out after 30 seconds, and returns
  schema-validated events with verbatim source evidence. The system instruction
  is versioned separately from the ADK runner and deterministic validators.
  Extraction records retain the source revision, prompt/extractor/model versions,
  candidate IDs, and evidence offsets. Invalid output produces zero candidates.
- Model-extracted URL and upload events always require explicit review. Confidence
  alone can never make them eligible for automatic Calendar writes.

## Known limitation

The retained corpus is intentionally not indexed yet; embeddings, retrieval,
chatbot, and MCP surfaces can be added later without re-fetching course data.

The URL guard resolves and validates DNS before the HTTP client connects, but it
does not pin that result through TLS. A hostile DNS server could theoretically
change its answer between validation and connection. For this single-user
hackathon build, only user-supplied course URLs are accepted; a production
multi-user version should use a network egress proxy that enforces destination
IP policy at connection time.
