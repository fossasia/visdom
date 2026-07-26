from sklearn.datasets import make_classification, make_regression
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, train_test_split

import visdom
from visdom.loggers import VisdomSklearnLogger


def main():
    # synthetic classification: 500 samples, 20 features, 2 classes
    X_clf, y_clf = make_classification(
        n_samples=500,
        n_features=20,
        n_informative=10,
        random_state=42,
    )
    X_train_clf, X_test_clf, y_train_clf, y_test_clf = train_test_split(
        X_clf, y_clf, test_size=0.2, random_state=42
    )

    # synthetic regression: 500 samples, 20 features
    X_reg, y_reg = make_regression(
        n_samples=500,
        n_features=20,
        noise=0.1,
        random_state=42,
    )
    X_train_reg, X_test_reg, y_train_reg, y_test_reg = train_test_split(
        X_reg, y_reg, test_size=0.2, random_state=42
    )

    viz = visdom.Visdom()
    VisdomSklearnLogger.autolog(viz, env="sklearn_run")

    # plain classifier -> text pane (dataset, train_score, fit_time, params)
    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X_train_clf, y_train_clf)

    # plain regressor -> text pane (dataset, train_score, fit_time, params)
    reg = Ridge(alpha=1.0)
    reg.fit(X_train_reg, y_train_reg)

    # grid search -> bar chart of mean_test_score + best params text pane
    param_grid = {
        "n_estimators": [50, 100, 200],
        "max_depth": [3, 5, None],
    }
    gs = GridSearchCV(
        RandomForestClassifier(random_state=42),
        param_grid,
        cv=3,
        scoring="accuracy",
    )
    gs.fit(X_train_clf, y_train_clf)

    print("RF accuracy:     {:.4f}".format(clf.score(X_test_clf, y_test_clf)))
    print("Ridge R2:        {:.4f}".format(reg.score(X_test_reg, y_test_reg)))
    print("GridSearch best: {:.4f}  params: {}".format(gs.best_score_, gs.best_params_))


if __name__ == "__main__":
    main()
