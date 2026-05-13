## Record found but asked field missing — followup phrasing

When STRUCTURED LIVE FACTS / OPERATIONAL RECORDS DID return the product /
service / order the customer asked about, but the specific field they
asked for is the `(not on file)` sentinel, the draft must:

(a) confirm we found the record by citing `catalog_no` / `doc_number` /
    `name`,
(b) state the asked field is not on file, and
(c) propose a concrete next step.

Confirming the match is NOT volunteering adjacent fields; it frames the
gap honestly so the customer knows we have the record and can act.

Use the next-step phrasing that matches the record kind:

- **Catalog products** (records with a `catalog_no` — e.g. an antibody
  SKU whose price simply isn't loaded into our DB): the price exists,
  we just need to look it up. Phrase the follow-up as confirming the
  listed catalog price, NOT a custom quote. Example: "I can confirm the
  catalog price for you — could you let me know the host species /
  clone / format you need so I pull the right SKU?" Do NOT default to
  "custom quote" / "sales team will follow up with a quote" wording for
  catalog SKUs; that framing implies a bespoke project where one isn't
  needed and may push the customer onto a slower path.

- **Service-flyer records** (records with `_subsource: service_flyer`,
  `plan_name` / `phase_name` / `pricing_tier` — e.g. a CAR-T or
  stable-cell-line development package): pricing is project-shaped.
  Phrase the follow-up as a custom quote. Example: "I can have our
  sales team send a custom quote — could you share the quantity /
  project scope?"

- **Operational records** (orders / invoices / shipping with a missing
  field): phrase the follow-up as looping in the right internal team.
  Example: "let me loop in the product / shipping team to confirm
  lead time / tracking."
