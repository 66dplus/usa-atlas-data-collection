# Data-side map backlog review — D1–D6

Two independent sessions are combined here. The implementation is an opt-in,
read-only consumer layer; ingestion and UI wiring retain their existing behavior.

| Tasks | Result | Review |
|---|---|---|
| D1, D2, D5 | Exact 35-field registry, 44 versioned definitions, corrected ACS formulas, explicit units and raw components | [Metric registry and examples](map-metrics/README.md) |
| D3, D4, D6 | Official-national selection, weighted BLS aggregate, Oregon AGI disclosure audit, comparison compatibility and per-level statistical domains | [Aggregate evidence and policies](map-aggregates/README.md) |

The integration checks pass actual preserved BLS/IRS inputs through the metric
definitions into the aggregate policies, and formula results into comparison.
Run all 38 tests from the repository root:

```bash
python3 -m unittest full.test_map_metrics database.test_map_aggregates database.test_map_metric_integration
```

Product choices remain explicit: six broad categorical fields, all-owner versus
mortgage-only costs, owner/renter ratio versus shares, and total AGI versus AGI
per return. Crime rates additionally need compatible annual reporting-population
inputs; IRS map comparisons need verified geographic vintage. These gaps do not
silently become guessed values. UI selection, labels, color scaling and Compare
presentation require later frontend integration.

The separate design-lab renderer branch compares the frozen SVG runtime with an
optional WebGL renderer. It retains the same source values, independently of
these new metric definitions, so renderer comparisons do not change statistics.
