import xgboost as xgb
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split

import visdom
from visdom.loggers import VisdomXGBLogger


def main():
    # synthetic classification: 500 samples, 20 features, 2 classes
    X, y = make_classification(
        n_samples=500,
        n_features=20,
        n_informative=10,
        random_state=42,
    )
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    viz = visdom.Visdom()
    VisdomXGBLogger.autolog(viz, env="xgboost_run")

    # functional API -> train/eval logloss curves logged automatically
    dtrain = xgb.DMatrix(X_train, label=y_train)
    dtest = xgb.DMatrix(X_test, label=y_test)
    booster = xgb.train(
        {"objective": "binary:logistic", "eval_metric": "logloss"},
        dtrain,
        num_boost_round=50,
        evals=[(dtrain, "train"), (dtest, "eval")],
    )

    # sklearn API -> same curves logged automatically via patched fit()
    clf = xgb.XGBClassifier(n_estimators=50, eval_metric="logloss")
    clf.fit(X_train, y_train, eval_set=[(X_test, y_test)])

    preds = (booster.predict(dtest) > 0.5).astype(int)
    accuracy = (preds == y_test).mean()
    print("Booster accuracy: {:.4f}".format(accuracy))
    print("XGBClassifier accuracy: {:.4f}".format(clf.score(X_test, y_test)))


if __name__ == "__main__":
    main()
