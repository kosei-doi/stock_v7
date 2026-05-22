"""円建て金額の切り捨てヘルパー。"""
from core.utils.money import yen_floor


def test_yen_floor_truncates_fraction():
    assert yen_floor(1234.99) == 1234
    assert yen_floor(1234.01) == 1234


def test_yen_floor_negative():
    assert yen_floor(-10.9) == -11


def test_yen_floor_none_and_invalid():
    assert yen_floor(None) == 0
    assert yen_floor("bad") == 0
