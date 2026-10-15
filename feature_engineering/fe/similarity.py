"""TF-IDF (di-fit hanya pada akun latih) dan fitur `similarity`."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from .settings import FeatureEngineeringError

TOLERANCE = 1e-9


def _vectorizer(cfg: dict) -> TfidfVectorizer:
    t = cfg["tfidf"]
    return TfidfVectorizer(
        tokenizer=str.split, token_pattern=None, lowercase=False, preprocessor=None,
        ngram_range=tuple(t["ngram_range"]), min_df=t["min_df"], max_df=t["max_df"],
        sublinear_tf=t["sublinear_tf"], smooth_idf=t["smooth_idf"], norm=t["norm"],
    )


def similarity_for_split(docs: pd.Series, train_pos: np.ndarray, test_pos: np.ndarray, cfg: dict) -> dict:
    texts = docs.fillna("").astype(str).to_numpy()
    if cfg["tfidf"]["norm"] != "l2":
        raise FeatureEngineeringError("Rumus similarity mengandaikan vektor ternormalisasi L2 (tfidf.norm = 'l2').")
    vec = _vectorizer(cfg)
    x_train = vec.fit_transform(texts[train_pos])
    x_test = vec.transform(texts[test_pos])
    n_train = x_train.shape[0]
    if n_train < 2:
        raise FeatureEngineeringError("similarity butuh minimal 2 akun latih.")

    s = np.asarray(x_train.sum(axis=0)).ravel()
    self_dot = np.asarray(x_train.multiply(x_train).sum(axis=1)).ravel()
    sim_train = (x_train @ s - self_dot) / (n_train - 1)
    sim_test = (x_test @ s) / n_train

    for name, arr in (("train", sim_train), ("test", sim_test)):
        if np.isnan(arr).any() or arr.min() < -TOLERANCE or arr.max() > 1 + TOLERANCE:
            raise FeatureEngineeringError(f"similarity {name} di luar [0, 1]: min {arr.min()}, max {arr.max()}")
    return {
        "train": np.clip(sim_train, 0.0, 1.0),
        "test": np.clip(sim_test, 0.0, 1.0),
        "n_fit_docs": int(n_train),
        "vocabulary_size": int(len(vec.vocabulary_)),
        "vectorizer": vec,
        "empty_docs_train": int((self_dot == 0).sum()),
        "empty_docs_test": int((np.asarray(x_test.multiply(x_test).sum(axis=1)).ravel() == 0).sum()),
    }
