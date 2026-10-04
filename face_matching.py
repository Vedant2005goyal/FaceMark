"""Face encoding and matching logic shared by the attendance app and the benchmarks.

Kept free of database and camera code so it can be benchmarked and unit-tested
on its own; register_faces.py and attendance.py both call into it.
"""
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import face_recognition


def encode_largest_face(image: np.ndarray, model: str = 'hog') -> Tuple[Optional[np.ndarray], Optional[tuple]]:
    """Return the 128-d encoding and (top, right, bottom, left) box of the largest face in an RGB image."""
    face_locations = face_recognition.face_locations(image, model=model)
    if not face_locations:
        return None, None
    largest = max(face_locations, key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3]))
    encodings = face_recognition.face_encodings(image, [largest])
    if not encodings:
        return None, None
    return encodings[0], largest


class FaceMatcher:
    """Nearest-neighbour matcher over a gallery that may hold several encodings per person.

    strategy='min'  -> distance to a person is the distance to their closest enrolled encoding
    strategy='mean' -> distance to a person is the distance to the mean of their encodings
    """

    def __init__(self, tolerance: float = 0.55, strategy: str = 'min'):
        if strategy not in ('min', 'mean'):
            raise ValueError(f"Unknown strategy: {strategy}")
        self.tolerance = tolerance
        self.strategy = strategy
        self._by_label: Dict[object, List[np.ndarray]] = defaultdict(list)
        self._labels: List[object] = []
        self._matrix = np.empty((0, 128))
        self._dirty = False

    def add(self, label, encoding: np.ndarray) -> None:
        self._by_label[label].append(np.asarray(encoding, dtype=np.float64))
        self._dirty = True

    def _rebuild(self) -> None:
        labels, rows = [], []
        for label, encs in self._by_label.items():
            if self.strategy == 'mean':
                labels.append(label)
                rows.append(np.mean(encs, axis=0))
            else:
                labels.extend([label] * len(encs))
                rows.extend(encs)
        self._labels = labels
        self._matrix = np.vstack(rows) if rows else np.empty((0, 128))
        self._dirty = False

    def __len__(self) -> int:
        return len(self._by_label)

    def nearest(self, encoding: np.ndarray) -> Tuple[Optional[object], float]:
        """Closest identity and its distance, ignoring the tolerance."""
        if self._dirty:
            self._rebuild()
        if not self._labels:
            return None, float('inf')
        distances = np.linalg.norm(self._matrix - encoding, axis=1)
        idx = int(np.argmin(distances))
        return self._labels[idx], float(distances[idx])

    def match(self, encoding: np.ndarray) -> Tuple[Optional[object], float]:
        """Closest identity if it is within tolerance, else (None, distance)."""
        label, distance = self.nearest(encoding)
        if label is None or distance > self.tolerance:
            return None, distance
        return label, distance


class ConfirmationTracker:
    """Only confirm an identity after it has matched in `required` consecutive processed frames.

    A single-frame false match (motion blur, look-alike at an angle) then can't mark
    someone present on its own.
    """

    def __init__(self, required: int = 3):
        self.required = max(1, required)
        self._streaks: Dict[object, int] = {}

    def update(self, labels_in_frame) -> List[object]:
        """Feed the identities matched in one processed frame; returns those newly confirmed."""
        seen = set(labels_in_frame)
        self._streaks = {label: self._streaks.get(label, 0) + 1 for label in seen}
        return [label for label, streak in self._streaks.items() if streak == self.required]
