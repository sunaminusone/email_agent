## Service-flyer pricing — how to use the records

Pricing records sourced from service flyers (records with `_subsource:
service_flyer`) describe development plans, often broken into phases.
They are pre-serialized but their drafting semantics aren't obvious:

- **Plan total vs phase price**. A record with `plan_total_price` set
  IS the bundled plan total — cite it directly when the customer asks
  about plan cost. A record with `phase_price` (and `phase_name` /
  `plan_name` set) is ONE phase of a multi-phase plan; its price is
  the phase price, NOT the plan total.
- **Don't sum phases yourself**. Either cite `plan_total_price`
  directly, or — if no record carries it — say the plan-level total
  isn't in the data and list phase prices with their plan/phase context
  (e.g. "Plan A · Phase III: $7,350 — vector construction"), noting
  that the full quote depends on selected phases.
- **`is_optional: true`** means that phase is not always included — its
  price only applies if the customer chooses to include it. Surface
  the optional flag when listing phase prices.
- **`price_min` / `price_max`** indicate a price range for the phase
  (typically batch-size or scope dependent); quote both bounds when
  present rather than picking one.
