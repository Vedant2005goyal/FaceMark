import numpy as np
import pytest

from face_matching import ConfirmationTracker, FaceMatcher


def unit(i, dim=128):
    v = np.zeros(dim)
    v[i] = 1.0
    return v


def test_empty_gallery_matches_nothing():
    assert FaceMatcher().match(unit(0)) == (None, float('inf'))


def test_match_within_tolerance():
    m = FaceMatcher(tolerance=0.5)
    m.add('alice', unit(0))
    m.add('bob', unit(1))
    label, dist = m.match(unit(0) + 0.01)
    assert label == 'alice'
    assert dist < 0.5


def test_reject_beyond_tolerance_but_nearest_still_reported():
    m = FaceMatcher(tolerance=0.5)
    m.add('alice', unit(0))
    assert m.match(unit(1))[0] is None
    assert m.nearest(unit(1))[0] == 'alice'


def test_min_strategy_uses_closest_enrolled_photo():
    m = FaceMatcher(tolerance=0.1, strategy='min')
    m.add('alice', unit(0))
    m.add('alice', unit(1))
    assert m.match(unit(1))[0] == 'alice'
    assert len(m) == 1


def test_mean_strategy_uses_centroid():
    m = FaceMatcher(tolerance=0.1, strategy='mean')
    m.add('alice', unit(0))
    m.add('alice', unit(1))
    # each single photo is ~0.71 from the centroid, so neither matches under a tight tolerance
    assert m.match(unit(1))[0] is None
    assert m.match((unit(0) + unit(1)) / 2)[0] == 'alice'


def test_unknown_strategy_rejected():
    with pytest.raises(ValueError):
        FaceMatcher(strategy='median')


def test_confirmation_needs_consecutive_frames():
    t = ConfirmationTracker(required=3)
    assert t.update(['alice']) == []
    assert t.update(['alice']) == []
    assert t.update(['alice']) == ['alice']
    assert t.update(['alice']) == []  # fires once per streak


def test_confirmation_streak_resets_when_face_missing():
    t = ConfirmationTracker(required=2)
    t.update(['alice'])
    t.update([])
    assert t.update(['alice']) == []
    assert t.update(['alice']) == ['alice']


def test_confirmation_of_one_frame_is_immediate():
    assert ConfirmationTracker(required=1).update(['bob']) == ['bob']
