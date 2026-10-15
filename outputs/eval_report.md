# Evaluation Report

## 1. Verdict accuracy
- Correct verdicts: 11 / 11
- Verdict accuracy: 100.0%

## 2. Cited-note exact match
- Justified rows: 3
- Correct note citations: 3 / 3
- Cited-note accuracy: 100.0%

## 3. Fabrication count
- Fabrications: 0 (must be 0)

## 4. Numeric-field match on sample rows
- Fields matching sample exactly: 9 / 9
- Sample match rate: 100.0%

## 5. Independent audit of justified rows
Re-reads `data/context_notes.csv` directly (not `config/notes_registry.yaml`) and checks:
route match, window overlap, and that the note text describes a cost rise.

- PASS | Ahmedabad-Mumbai 2025-01-20 N002 | all checks passed
- PASS | Chennai-Bangalore 2025-02-24 N001 | all checks passed
- PASS | Chennai-Bangalore 2025-03-03 N001 | all checks passed

## 6. Mutation tests
Each justified row must flip to unexplained when its matching note is corrupted.

- PASS | Ahmedabad-Mumbai 2025-01-20 N002 | date_shifted_3_weeks
- PASS | Ahmedabad-Mumbai 2025-01-20 N002 | route_swapped
- PASS | Ahmedabad-Mumbai 2025-01-20 N002 | text_no_effect
- PASS | Chennai-Bangalore 2025-02-24 N001 | date_shifted_3_weeks
- PASS | Chennai-Bangalore 2025-02-24 N001 | route_swapped
- PASS | Chennai-Bangalore 2025-02-24 N001 | text_no_effect
- PASS | Chennai-Bangalore 2025-03-03 N001 | date_shifted_3_weeks
- PASS | Chennai-Bangalore 2025-03-03 N001 | route_swapped
- PASS | Chennai-Bangalore 2025-03-03 N001 | text_no_effect

## 7. Retrieval-only ablation
Wrong-window cases where the rule-based gate correctly says unexplained,
but semantic retrieval still ranks the off-window note in the top 3.

- Chennai-Bangalore 2025-03-10 | gate=Yes | retrieval top-3=['N003', 'N001', 'N002'] | off-window note in top-3=True
- Chennai-Bangalore 2025-03-17 | gate=Yes | retrieval top-3=['N001', 'N003', 'N002'] | off-window note in top-3=True

**Overall result:** PASS. Verdicts are grounded, independently auditable, and robust to note mutations. Retrieval alone is insufficient for trustworthy justification.