# Reproducibility Report

Model: openai/gpt-oss-120b

## SHA-256 of outputs/flagged_routes.csv across three clean runs at temperature 0

| Run | Hash |
|-----|------|
| 1   | CD022D4BD9F371D019B4AD872CA7FD547D14D2F2D3B0BECE47175E0ACDC88416 |
| 2   | CD022D4BD9F371D019B4AD872CA7FD547D14D2F2D3B0BECE47175E0ACDC88416 |
| 3   | DC3ACBACF79DE13FC67E6D294B5EE5CDC14F9FEA754384399B17F5882F73072B |

**Hash comparison:** DIFFERENT

## Non-reason column comparison: temp 0 vs temp 0.7

Columns compared: route, week_of, cost_per_tonne_km, vs_own_history, vs_similar_routes, flagged, matched_note_id

Non-reason columns identical: True
Rows compared: 11
Reason differences: 10

Row 0 | Delhi-Chennai 2024-02-05
  A: The freight cost rise for the Delhi-Chennai route in the week of 2024-02-05 has no supporting note; the closest note (N001, 2025-02-24) describes flooding on a different highway and does not justify this increase, so it is flagged for human review.
  B: No supporting note explains the cost rise for the Delhi-Chennai route in the week of 2024-02-05. It is flagged for human review. The closest note, N001 (2025-02-24), pertains to flooding on a different highway and does not justify this cost increase.

Row 1 | Delhi-Jaipur 2024-11-11
  A: No supporting note explains the freight cost rise for Delhi-Jaipur in the week of 2024-11-11. The closest note, N003 (2025-05-05), does not justify a rise on this route/week, so the alert is flagged for human review.
  B: No supporting note explains the freight cost rise for the Delhi-Jaipur route in the week of 2024-11-11. It is flagged for human review. The closest note, N003 (2025-05-05), does not justify a cost rise on this route/week.

Row 2 | Delhi-Jaipur 2024-11-18
  A: No supporting note explains the freight-cost rise for the Delhi-Jaipur route in the week of 2024-11-18. The closest note, N007 (2024-05-20), only reports improved road conditions and does not justify a cost increase, so this alert is flagged for human review.
  B: The cost increase for the Delhi-Jaipur route in the week of 2024-11-18 has no supporting note; the closest note, N007 (2024-05-20), reports road improvements and does not justify a rise. This alert is therefore flagged for human review.

Row 3 | Ahmedabad-Mumbai 2025-01-20
  A: Matches note N002 dated 2025-01-20: a regional festival week caused high demand and limited truck availability, leading transporters to apply a temporary surcharge on the Ahmedabad-Mumbai corridor, which explains the observed freight-cost rise.
  B: Matches note N002 dated 2025-01-20: a regional festival week caused high demand and limited truck availability, leading transporters to apply a temporary surcharge on the Ahmedabad-Mumbai corridor, which explains the observed freight-cost increase.

Row 4 | Chennai-Bangalore 2025-02-24
  A: Matches note N001 dated 2025-02-24: Heavy flooding on the Chennai-Bangalore highway blocked normal truck traffic, requiring longer detours and increasing trip expenses during the period.
  B: Matches note N001 dated 2025-02-24: heavy flooding on the Chennai-Bangalore highway blocked normal truck routes, requiring longer detours and increasing trip expenses during the period.

Row 5 | Chennai-Bangalore 2025-03-03
  A: Matches note N001 dated 2025-02-24: Heavy flooding on the Chennai-Bangalore highway forced trucks onto longer detours, increasing travel distance and fuel use, which raised freight costs during the week of 2025-03-03.
  B: Matches note N001 dated 2025-02-24: Heavy flooding on the Chennai-Bangalore highway forced trucks onto longer detours, disrupting normal movement and increasing trip expenses during the period.

Row 7 | Chennai-Bangalore 2025-03-17
  A: The freight cost increase for the Chennai-Bangalore route in the week of 2025-03-17 has no supporting note; the closest note N001 (2025-02-24) describes flooding that ended before this week and does not justify the rise. Flagged for human review.
  B: No supporting note explains the freight cost rise for the Chennai-Bangalore route in the week of 2025-03-17. Although note N001 (2025-02-24) mentions flooding, it ended before this week and does not justify the increase, so the alert is flagged for human review.

Row 8 | Mumbai-Delhi 2025-05-12
  A: No supporting note explains the freight cost rise for Mumbai-Delhi in the week of 2025-05-12. It is flagged for human review. The closest note, N002 (2025-01-20), refers to a different corridor and does not justify this increase.
  B: The freight cost rise for Mumbai-Delhi in the week of 2025-05-12 has no supporting note; the closest note N002 (2025-01-20) concerns a different corridor and does not justify this increase. It is flagged for human review.

Row 9 | Mumbai-Pune 2025-09-15
  A: No supporting note explains the freight cost rise for Mumbai-Pune in the week of 2025-09-15. It is flagged for human review. Note N002 (2025-01-20) relates to a different corridor and does not justify this increase.
  B: No supporting note explains the freight-cost rise for Mumbai-Pune in the week of 2025-09-15. It is flagged for human review. Note N002 (2025-01-20) relates to a different corridor and does not justify this cost increase.

Row 10 | Mumbai-Pune 2025-11-17
  A: No supporting note explains the freight cost rise for Mumbai-Pune week of 2025-11-17. It is flagged for human review. Note N002 (2025-01-20) refers to a different corridor and does not justify this increase.
  B: No supporting note explains the freight cost rise for Mumbai-Pune in the week of 2025-11-17. The closest note, N002 (2025-01-20), relates to a different corridor and does not justify this increase. The alert is therefore flagged for human review.


## Interpretation
WARNING: hashes differ across the three temperature-0 runs.  With a hosted API (e.g., Groq), inference is not guaranteed bit-deterministic even at temperature 0 with a fixed seed (server-side batching, rate-limit retries).  The diff above shows only reason-wording differences.

The important guarantee holds: the structured columns (route, week_of, cost_per_tonne_km, vs_own_history, vs_similar_routes, flagged, matched_note_id) are identical across every run, at temperature 0 and 0.7 alike.  Only the reason wording may vary.  Verdicts and citations come from the deterministic rule gate, never from the LLM, so wording variation cannot affect correctness.

Generated: 2026-10-15T06:38:29Z

