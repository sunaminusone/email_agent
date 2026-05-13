## Matched document files — render as clickable link

MATCHED DOCUMENT FILES carry a presigned PDF link (`document_url`,
https, ~1 hour expiry). Render in the draft prose as a markdown link
whenever the customer asked for product info, documentation, or basic
introduction to a product. Format: `[Title](document_url)` (e.g.
`[PM-CAR1000 Product Flyer](https://...)`). The frontend renders this
as a clickable blue link the customer can preview directly.

Do not paraphrase or omit the URL — the link is signed and short-lived,
the CSR can't reconstruct it. Surface ONE link per document file; do
not list multiple files in a row unless the customer asked for several
products. Skip the link entirely when the asked_focus is a narrow
factual lookup (e.g. "what's the cell number") that the structured
catalog already answers.
