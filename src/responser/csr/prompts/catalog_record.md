## Catalog records — schema hints

Catalog record fields are pre-serialized for you. Field names (e.g.
`wb_dilution`, `construct`, `lnp_type`, `formulation`, `storage`,
`shipping`, `data_sheet_url`) are self-describing; match them to the
customer's ask. Empty / missing fields are already omitted from the
record — if the field the customer asked about isn't there, say so per
the general ASKED FOCUS rule. When a field carries free-form citation
text (e.g. `references_text`, `immunogen`), quote it verbatim; if HTML
markup is present, extract the citation/description text and drop raw
`<br />` etc.
