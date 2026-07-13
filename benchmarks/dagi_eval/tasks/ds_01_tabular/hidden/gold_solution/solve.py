"""Gold DS solution: gradient boosting, trap dropped, missingness features."""
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import OrdinalEncoder


def main():
    train = pd.read_csv("train.csv")
    test = pd.read_csv("test_features.csv")
    y = train["label"]
    X = train.drop(columns=["id", "label", "audit_flag"])
    Xt = test.drop(columns=["id", "audit_flag"])
    for c in ("x3", "x7"):
        X[f"{c}_missing"] = X[c].isna().astype(int)
        Xt[f"{c}_missing"] = Xt[c].isna().astype(int)
    cat = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]
    enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    X[cat] = enc.fit_transform(X[cat])
    Xt[cat] = enc.transform(Xt[cat])
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.08,
                                         random_state=0)
    clf.fit(X, y)
    pd.DataFrame({"id": test["id"],
                  "probability": clf.predict_proba(Xt)[:, 1]}).to_csv(
        "predictions.csv", index=False)


if __name__ == "__main__":
    main()
