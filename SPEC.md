# Specification

## 1. Definitions from the brief

1. **Weekly cost per tonne-km**: For each route and week, compute
   `cost_per_tonne_km = total_freight_cost / total(quantity_tonnes * distance_km)`
   using all shipments in that route-week group.
2. **Week boundaries**: Weeks run Monday to Sunday; `week_of` is that week's Monday date.
   Shipment dates are grouped into these weeks before any cost computation.
3. **Own-history baseline**: The route's trailing 8-week rolling average cost per tonne-km,
   using only weeks strictly before the current week (no look-ahead). If fewer than 8 prior
   weeks exist, use all prior weeks available; do not pad or extrapolate.
4. **Peer baseline**: The average cost per tonne-km in the same week across all other routes
   that share the same `route_type` (Short / Medium / Long). The route itself is excluded
   from its own peer average.

## 2. Output contract

Columns in this exact order:

```
route,week_of,cost_per_tonne_km,vs_own_history,vs_similar_routes,flagged,matched_note_id,reason
```

- `route`: origin-destination pair, e.g. `Delhi-Jaipur`.
- `week_of`: Monday date of the week, formatted as `YYYY-MM-DD`.
- `cost_per_tonne_km`: weekly pooled ratio (see §1).
- `vs_own_history`: percentage difference vs own-history baseline.
- `vs_similar_routes`: percentage difference vs peer baseline.
- `flagged`: `Yes` if the rise is unexplained; `No (justified)` if a supporting note is found.
- `matched_note_id`: blank when unexplained; otherwise the note ID that justifies the row.
- `reason`: plain-English explanation of the verdict; if justified, must name the note and
  reflect its content and dates.

## 3. Guardrails

1. A `No (justified)` verdict must cite a note that:
   - applies to that route (or `All Routes`), **and**
   - applies to that time window, **and**
   - describes a cost rise.
2. If no supporting note is found, the verdict must be unexplained (`Yes`, flagged).
3. Across repeated runs on the same input, the verdict, cited note, and numbers must be
   identical. Explanation wording may vary.

## 4. Design decisions

1. **History and peer aggregation**: use the pooled weekly ratio for each route-week, then
   take the unweighted mean of those weekly values for the own-history and peer baselines.
2. **Arithmetic**: use `Decimal` with `ROUND_HALF_UP` for all monetary and ratio math.
3. **N003 applicability window**: note `N003` (diesel price rise) is treated as applying only
   to the week of `2025-05-05`.
4. **Output scope**: the main output contains only candidate rows; non-candidate rows are
   not emitted.

## Open questions

1. **Flagging threshold**: the brief says "flag any route where the cost is rising and looks
   out of the ordinary" but does not define the percentage threshold or whether both
   `vs_own_history` and `vs_similar_routes` must exceed it.
2. **Format of `vs_own_history` and `vs_similar_routes`**: the brief calls these "numeric
   fields we grade" while `sample_output_format_v2.csv` contains strings such as
   `+35.5% vs this route's past average`. The exact required format is undefined.
3. **Definition of "candidate rows"**: it is unclear whether candidates are all route-weeks
   with sufficient data, only flagged route-weeks, or only route-weeks that show a cost rise.
4. **Decimal precision**: the brief/sample do not specify the number of decimal places for
   `cost_per_tonne_km` or the percentage fields.
5. **Time-window semantics for non-N003 notes**: several notes describe multi-week events
   (e.g. `N001` spans Feb 24 to Mar 8) or vague timing (e.g. `N002` "festival week");
   the exact window for matching is not specified.
6. **"Rising" directionality**: the brief says "cost is rising" but also "out of the
   ordinary compared to ... similar routes"; it is unclear whether significant cost
   decreases should also be flagged.
7. **Zero prior weeks**: the brief says use all prior weeks if fewer than 8 exist, but does
   not state whether a route-week with zero prior weeks should still be emitted or how
   `vs_own_history` should be represented.
8. **Sample output filename mismatch**: the brief references `sample_output_format.csv` but
   the supplied file is `sample_output_format_v2.csv`.
