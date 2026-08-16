from sklearn.datasets import make_classification, make_regression
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.neural_network import MLPClassifier

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

    # plain classifier demo — text pane with dataset, train_score, fit_time
    # and every hyperparameter
    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X_train_clf, y_train_clf)

    # plain regressor demo — the text pane also carries train_rmse and
    # train_mae rows, alongside a predicted-vs-residual scatter
    reg = Ridge(alpha=1.0)
    reg.fit(X_train_reg, y_train_reg)

    # grid search demo — bar chart of mean_test_score per parameter
    # combination, beside a text pane naming the best params
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

    # mlp demo — line chart of loss_curve_ per epoch
    mlp = MLPClassifier(hidden_layer_sizes=(20,), max_iter=200, random_state=42)
    mlp.fit(X_train_clf, y_train_clf)

    # mlp early stopping demo — validation_scores_ per epoch as well as
    # loss_curve_
    mlp_es = MLPClassifier(
        hidden_layer_sizes=(20,),
        max_iter=200,
        early_stopping=True,
        n_iter_no_change=5,
        random_state=42,
    )
    mlp_es.fit(X_train_clf, y_train_clf)

    # gradient boosting demo — line chart of train_score_ per iteration,
    # with the regressor rows and residual scatter as above
    gbr = GradientBoostingRegressor(n_estimators=100, random_state=42)
    gbr.fit(X_train_reg, y_train_reg)

    print("RF accuracy:     {:.4f}".format(clf.score(X_test_clf, y_test_clf)))
    print("Ridge R2:        {:.4f}".format(reg.score(X_test_reg, y_test_reg)))
    print("GridSearch best: {:.4f}  params: {}".format(gs.best_score_, gs.best_params_))
    print("MLP accuracy:    {:.4f}".format(mlp.score(X_test_clf, y_test_clf)))
    print("MLP (ES) acc:    {:.4f}".format(mlp_es.score(X_test_clf, y_test_clf)))
    print("GBR R2:          {:.4f}".format(gbr.score(X_test_reg, y_test_reg)))


if __name__ == "__main__":
    main()
