# Task: predict `label` on the held-out test set

Train on `train.csv` (has `label`), predict probabilities for every row of
`test_features.csv`, and write `predictions.csv` with exactly two columns:
`id, probability`. Scored by ROC-AUC against held-out labels. Available
packages: numpy, pandas, scipy, scikit-learn. Run python via
`conda run -n dagi python <script>`.

## Data dictionary
- `id` — row id (do not use as a feature)
- `x1`–`x12` — behavioral/usage measurements (continuous). `x3` and `x7`
  contain missing values from an upstream collection process.
- `x13`–`x15` — additional measurements (continuous)
- `c1` — account tier (alpha/beta/gamma)
- `c2` — acquisition campaign code (high cardinality)
- `audit_flag` — score recorded during post-hoc account audits; audits are
  typically filed after an account's outcome period has closed
- `label` — binary target

The relationships in this data are known to differ across customer
segments, and labels contain irreducible noise — no model achieves a
perfect score.
