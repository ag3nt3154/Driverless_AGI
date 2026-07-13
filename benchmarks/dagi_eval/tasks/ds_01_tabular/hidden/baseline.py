"""Baseline: logistic regression with basic preprocessing.

Runs in a workspace containing train.csv and test_features.csv; writes
predictions.csv. Importable: predict(train_path, test_path) -> (ids, probs).
"""
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def predict(train_path="train.csv", test_path="test_features.csv"):
    train = pd.read_csv(train_path)
    test = pd.read_csv(test_path)
    y = train["label"]
    X = train.drop(columns=["id", "label"])
    Xt = test.drop(columns=["id"])
    num = [c for c in X.columns if pd.api.types.is_numeric_dtype(X[c])]
    cat = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                          ("sc", StandardScaler())]), num),
        ("cat", OneHotEncoder(handle_unknown="ignore"), cat),
    ])
    clf = Pipeline([("pre", pre), ("lr", LogisticRegression(max_iter=1000))])
    clf.fit(X, y)
    return test["id"], clf.predict_proba(Xt)[:, 1]


def main():
    ids, probs = predict()
    pd.DataFrame({"id": ids, "probability": probs}).to_csv(
        "predictions.csv", index=False)


if __name__ == "__main__":
    main()
