## Operational records — schema hints

OPERATIONAL RECORDS (orders / invoices / shipping / customers from
QuickBooks) are authoritative — cite `doc_number`, `transaction_date`,
`payment_status`, tracking IDs, `billing_email`, etc. exactly as given.

Fields are pre-serialized for you:
- sentinels are resolved to booleans like `email_sent` / `printed`
- balances renamed to scope-explicit names —
  `outstanding_balance` is per-transaction;
  `total_outstanding_across_invoices` is per-customer (sum across all
  open invoices, NOT a per-invoice figure)
- `payment_status` is pre-derived with vocabulary `paid / open /
  partial / overdue (N days) / due today / due in N day(s)`, optionally
  suffixed `(not sent)` when the document is `email_queued`

Do NOT volunteer `payment_status` unless the customer asked about it.
