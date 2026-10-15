# FreightTiger - Business Insights

Generated: 2026-10-15T09:29:21Z

Sources: `data/shipment_records.csv` + `outputs/flagged_routes.csv`.

> Auxiliary report. The graded deliverable `outputs/flagged_routes.csv` is
> untouched and keeps its exact 8-column contract.

---

## 1. Financial impact triage (INR excess vs 8-week baseline)

Excess = actual freight spend - (route trailing-8-week cost/tonne-km × tonne-km)
for that week. Positive = spend above the route's own recent norm.

### 1a. Justified surge spend (real-world reason found)

| Route | Week | Note | Excess (INR) |
|---|---|---|---:|
| Ahmedabad-Mumbai | 2025-01-20 | N002 | ₹30,647 |
| Chennai-Bangalore | 2025-02-24 | N001 | ₹28,752 |
| Chennai-Bangalore | 2025-03-03 | N001 | ₹18,560 |
| **Total** | **3 weeks** | | **₹77,960** |

### 1b. Unexplained financial leakage (ranked by Rupee impact)

| Rank | Route | Week | Excess (INR) |
|---:|---|---|---:|
| 1 | Delhi-Jaipur | 2024-11-11 | ₹22,118 |
| 2 | Delhi-Chennai | 2024-02-05 | ₹22,107 |
| 3 | Chennai-Bangalore | 2025-03-10 | ₹20,842 |
| 4 | Mumbai-Delhi | 2025-05-12 | ₹17,702 |
| 5 | Chennai-Bangalore | 2025-03-17 | ₹12,373 |
| 6 | Delhi-Jaipur | 2024-11-18 | ₹7,933 |
| 7 | Mumbai-Pune | 2025-09-15 | ₹2,896 |
| 8 | Mumbai-Pune | 2025-11-17 | ₹2,492 |
| | **Total** | **8 weeks** | **₹1,08,463** |

**Total excess across all flagged weeks: ₹1,86,423** (₹77,960 justified + ₹1,08,463 unexplained).

---

## 2. Transporter-level drilldown (corridor-wide vs split)

For each flagged week, every active transporter's cost/tonne-km is compared
with its own trailing-8-week average on that route.

- **Delhi-Chennai 2024-02-05** [Yes] - mixed: Trident Carriers +10.4%, Shivam Freight Co +5.3%
- **Delhi-Jaipur 2024-11-11** [Yes] - corridor-wide: Speedway Logistics +37.3%, Om Sai Transport +36.0%, Trident Carriers +32.8%
- **Delhi-Jaipur 2024-11-18** [Yes] - corridor-wide: Bharat Roadways +31.4%, Om Sai Transport +31.4%
- **Ahmedabad-Mumbai 2025-01-20** [No (justified)] - corridor-wide: Trident Carriers +30.1%, Bharat Roadways +29.5%, Om Sai Transport +25.6%
- **Chennai-Bangalore 2025-02-24** [No (justified)] - corridor-wide: Speedway Logistics +34.6%, Om Sai Transport +33.3%, Bharat Roadways +33.3%
- **Chennai-Bangalore 2025-03-03** [No (justified)] - corridor-wide: Bharat Roadways +24.3%, Shivam Freight Co +23.2%, Trident Carriers +20.1%
- **Chennai-Bangalore 2025-03-10** [Yes] - corridor-wide: Om Sai Transport +25.0%, Shivam Freight Co +23.3%, Bharat Roadways +20.8%
- **Chennai-Bangalore 2025-03-17** [Yes] - corridor-wide: Speedway Logistics +23.3%, Trident Carriers +20.7%, Om Sai Transport +16.4%
- **Mumbai-Delhi 2025-05-12** [Yes] - corridor-wide: Om Sai Transport +12.2%, Trident Carriers +12.0%
- **Mumbai-Pune 2025-09-15** [Yes] - mixed: Bharat Roadways +10.8%, Trident Carriers +7.3%
- **Mumbai-Pune 2025-11-17** [Yes] - corridor-wide: Trident Carriers +13.9%, Om Sai Transport +13.3%, Speedway Logistics +8.8%

Percentages are vs each carrier's own trailing-8-week average on that route.
Delivery note: the *count* and *identity* of top movers is the signal, not tiny
differences in the percentages.

**Case studies**

- **Delhi-Jaipur 2024-11-11** - all three active carriers rose together
  (~+33% to +37%), so the move is corridor-wide rather than a single-carrier
  artefact. **No note explains this week**, so it remains flagged for human review.
- **Chennai-Bangalore 2025-03-17** - **unexplained**: the week follows the end of the
  N001 window (2025-02-24..2025-03-08), and N009 states conditions were back to normal
  by 2025-03-17, so no note justifies it. Every active carrier is still above its
  trailing average; Speedway Logistics (+23.3%) and Trident Carriers (+20.7%) are the
  highest (this is a description of the data, not an asserted cause).

---

## 3. Structural limitation of trailing rolling windows (the Mumbai-Pune slow creep)

Comparison of the first 8 weeks of 2024 with the last 8 weeks of 2025:

| Route | First 8w 2024 | Last 8w 2025 | 2-year change |
|---|---:|---:|---:|
| Ahmedabad-Mumbai | 2.536 | 2.720 | +7.2% |
| Chennai-Bangalore | 2.719 | 2.876 | +5.8% |
| Delhi-Chennai | 2.079 | 2.034 | -2.1% |
| Delhi-Jaipur | 3.048 | 3.271 | +7.3% |
| Kolkata-Bhubaneswar | 2.612 | 2.766 | +5.9% |
| Mumbai-Delhi | 2.051 | 2.158 | +5.2% |
| Mumbai-Pune | 3.338 | 4.293 | +28.6%  (creep) |

**The discovery.** Six of seven routes drifted only -2% to +7% over two years (consistent with the 5-7% diesel note N003). **Mumbai-Pune crept +28.6%** (3.34 -> 4.29 INR/tonne-km).

Because the required `vs_own_history` baseline is a *trailing 8-week rolling mean*, a slow creep (median about +1%/week on Mumbai-Pune since mid-2025) lifts the baseline underneath itself. The 8-week window therefore only trips when the creep temporarily out-runs its own baseline (2025-09-15 +9.2% and 2025-11-17 +8.9%) - far fewer alarms than a procurement team would want for a lane that is +28.6% over two years.

**Recommendation.** Keep the mandated 8-week baseline for scoring, but add a long-horizon check (e.g. drift vs the same route 6/12 months ago, and spread vs peer corridors) to surface silent rate creep that a short rolling window absorbs by design.

---

### How to reproduce

```
python src/main.py        # produces outputs/flagged_routes.csv
python src/insights.py    # produces outputs/business_insights.md
```
