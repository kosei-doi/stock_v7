"""scoring のユニットテスト（_combine_scores の ValueError）。"""
from __future__ import annotations

import pytest
from core.dvc.scoring import _combine_scores


def test_combine_scores_length_mismatch_raises():
    with pytest.raises(ValueError, match="長さが一致しません"):
        _combine_scores([1.0, 2.0], [0.5])


def test_combine_scores_ok():
    r = _combine_scores([10.0, 20.0], [0.5, 0.5])
    assert r == pytest.approx(15.0)
