# Fix cancel exit status and document custom request-ID syntax

`cancel` exits 1 when it succeeds, because the rendered record has status
cancelled; scripts using `set -e` cannot tell success from the refusal for a
running request without parsing JSON. Exit 0 when the cancel command itself
succeeds. Separately, `--request-id` accepts only `GENERATION:rUNIQUE`; the
help and guide document reuse but not construction, so the subject's first
deduplication test failed on every client until the error revealed the format.

Closed: Successful cancel exits 0; retrieval of cancelled work still exits 1. CLI help and guide document GENERATION:rUNIQUE_ID construction and reuse. Verified live.
