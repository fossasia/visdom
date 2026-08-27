#!/usr/bin/env python3
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import numpy as np
from tensorflow import keras
from tensorflow.keras import layers

import visdom
from visdom.loggers import VisdomKerasLogger


def main():
    # synthetic binary classification: 500 samples, 20 features
    rng = np.random.default_rng(42)
    X = rng.normal(size=(500, 20))
    y = (X[:, :10].sum(axis=1) > 0).astype("float32")
    X_train, X_val = X[:400], X[400:]
    y_train, y_val = y[:400], y[400:]

    viz = visdom.Visdom()
    logger = VisdomKerasLogger(viz, env="keras_run", log_every=5)

    model = keras.Sequential(
        [
            layers.Input(shape=(20,)),
            layers.Dense(32, activation="relu"),
            layers.Dense(1, activation="sigmoid"),
        ]
    )
    model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])

    model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=20,
        callbacks=[logger],
        verbose=0,
    )

    loss, accuracy = model.evaluate(X_val, y_val, verbose=0)
    print("Val accuracy: {:.4f}".format(accuracy))


if __name__ == "__main__":
    main()
