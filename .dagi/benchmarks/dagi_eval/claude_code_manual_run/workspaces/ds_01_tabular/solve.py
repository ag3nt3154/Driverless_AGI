"""
Train a predictive model on train.csv and produce predictions.csv for
test_features.csv (columns: id, probability).

Approach
--------
- Target: `label` (binary classification), scored by ROC-AUC.
- Features: x1-x15 (continuous, x3/x7 have missing values), c1 (low-card
  categorical, account tier), c2 (high-card categorical, campaign code),
  audit_flag (continuous, strongest single predictor and present in both
  train and test, so it is used as a normal feature).
- Spec notes relationships differ across segments (c1), so we let the
  model learn segment-conditional interactions rather than hand engineer
  them; a HistGradientBoostingClassifier does this natively via tree
  splits and also handles missing values and categoricals natively.
- Model: sklearn HistGradientBoostingClassifier with native categorical
  support for c1/c2 and native NaN handling for x3/x7. Hyperparameters
  chosen via a small grid evaluated with 5-fold stratified CV on
  train.csv (ROC-AUC).
- A regularized logistic regression on standardized/one-hot features is
  fit as a simple baseline/sanity check and blended in via a small
  weighted average if it improves CV AUC.
"""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

RANDOM_STATE = 42

NUM_COLS = [f"x{i}" for i in range(1, 16)] + ["audit_flag"]
CAT_COLS = ["c1", "c2"]
FEATURE_COLS = NUM_COLS + CAT_COLS


def load_data():
    train = pd.read_csv("train.csv")
    test = pd.read_csv("test_features.csv")
    return train, test


def build_hgb_pipeline(cat_cols, params=None):
    """HistGradientBoostingClassifier with native categorical + NaN support."""
    params = params or {}
    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", max_categories=None,
                                   sparse_output=False), []),
        ],
        remainder="passthrough",
    )
    # We instead rely on HGB's native categorical_features param, so no
    # preprocessing is needed except telling it which columns are categorical.
    model = HistGradientBoostingClassifier(
        random_state=RANDOM_STATE,
        categorical_features=cat_cols,
        **params,
    )
    return model


def add_interaction_features(df):
    """Add a handful of nonlinear/interaction terms for the strongest
    numeric predictors (x1, x13, audit_flag), since the target likely
    depends on quadratic/interaction effects of these on top of a
    largely linear/logistic relationship."""
    out = df.copy()
    out["x1_sq"] = out["x1"] ** 2
    out["x13_sq"] = out["x13"] ** 2
    out["audit_sq"] = out["audit_flag"] ** 2
    out["x1_x13"] = out["x1"] * out["x13"]
    out["x1_audit"] = out["x1"] * out["audit_flag"]
    out["x13_audit"] = out["x13"] * out["audit_flag"]
    return out


EXTRA_NUM_COLS = ["x1_sq", "x13_sq", "audit_sq", "x1_x13", "x1_audit", "x13_audit"]


def build_logreg_pipeline(num_cols, cat_cols):
    num_pipe = Pipeline(steps=[
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    cat_pipe = Pipeline(steps=[
        ("ohe", OneHotEncoder(handle_unknown="ignore")),
    ])
    pre = ColumnTransformer(transformers=[
        ("num", num_pipe, num_cols),
        ("cat", cat_pipe, cat_cols),
    ])
    clf = LogisticRegression(max_iter=2000, C=1.0, random_state=RANDOM_STATE)
    return Pipeline(steps=[("pre", pre), ("clf", clf)])


def prep_for_hgb(df):
    out = df[FEATURE_COLS].copy()
    for c in CAT_COLS:
        out[c] = out[c].astype("category")
    return out


def cv_auc(model_builder, X, y, n_splits=5):
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
    oof = np.zeros(len(y))
    for tr_idx, va_idx in skf.split(X, y):
        model = model_builder()
        model.fit(X.iloc[tr_idx], y.iloc[tr_idx])
        oof[va_idx] = model.predict_proba(X.iloc[va_idx])[:, 1]
    return roc_auc_score(y, oof), oof


def main():
    train, test = load_data()
    train = add_interaction_features(train)
    test = add_interaction_features(test)
    y = train["label"]

    lr_num_cols = NUM_COLS + EXTRA_NUM_COLS

    X_hgb = prep_for_hgb(train)
    X_hgb_test = prep_for_hgb(test)

    cat_idx = [X_hgb.columns.get_loc(c) for c in CAT_COLS]

    # Small hyperparameter search for HGB via CV AUC.
    candidate_params = [
        dict(max_iter=300, max_depth=None, learning_rate=0.05,
             l2_regularization=0.0, max_leaf_nodes=31),
        dict(max_iter=300, max_depth=None, learning_rate=0.05,
             l2_regularization=1.0, max_leaf_nodes=31),
        dict(max_iter=400, max_depth=6, learning_rate=0.05,
             l2_regularization=1.0, max_leaf_nodes=63),
        dict(max_iter=500, max_depth=4, learning_rate=0.03,
             l2_regularization=1.0, max_leaf_nodes=31),
    ]

    best_auc = -1
    best_params = None
    best_oof = None
    for params in candidate_params:
        builder = lambda p=params: build_hgb_pipeline(cat_idx, p)
        auc, oof = cv_auc(builder, X_hgb, y)
        print(f"HGB params={params} CV AUC={auc:.5f}")
        if auc > best_auc:
            best_auc = auc
            best_params = params
            best_oof = oof

    print(f"Best HGB CV AUC: {best_auc:.5f} with params {best_params}")

    # Logistic regression baseline / potential blend partner (with a few
    # quadratic/interaction terms for the strongest numeric predictors).
    lr_feature_cols = lr_num_cols + CAT_COLS

    def lr_builder():
        return build_logreg_pipeline(lr_num_cols, CAT_COLS)

    lr_auc, lr_oof = cv_auc(lr_builder, train[lr_feature_cols], y)
    print(f"LogReg (+interactions) CV AUC: {lr_auc:.5f}")

    # Try blending HGB + LR out-of-fold predictions to see if it helps.
    best_blend_auc = best_auc
    best_w = 1.0
    for w in np.arange(0.0, 1.01, 0.1):
        blend = w * best_oof + (1 - w) * lr_oof
        auc = roc_auc_score(y, blend)
        if auc > best_blend_auc:
            best_blend_auc = auc
            best_w = w
    print(f"Best blend weight on HGB={best_w:.2f}, blended CV AUC={best_blend_auc:.5f}")

    # Fit final model(s) on full training data.
    final_hgb = build_hgb_pipeline(cat_idx, best_params)
    final_hgb.fit(X_hgb, y)
    hgb_test_pred = final_hgb.predict_proba(X_hgb_test)[:, 1]

    if best_w < 0.999:
        final_lr = build_logreg_pipeline(lr_num_cols, CAT_COLS)
        final_lr.fit(train[lr_feature_cols], y)
        lr_test_pred = final_lr.predict_proba(test[lr_feature_cols])[:, 1]
        final_pred = best_w * hgb_test_pred + (1 - best_w) * lr_test_pred
        print(f"Using blend: {best_w:.2f} * HGB + {1 - best_w:.2f} * LR")
    else:
        final_pred = hgb_test_pred
        print("Using pure HGB predictions.")

    out = pd.DataFrame({"id": test["id"], "probability": final_pred})
    out.to_csv("predictions.csv", index=False)
    print("Wrote predictions.csv with shape", out.shape)
    print(out.head())


if __name__ == "__main__":
    main()
