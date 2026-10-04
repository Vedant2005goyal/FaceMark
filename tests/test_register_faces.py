import os

import pytest

from register_faces import FaceRegistration, RegistrationError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTO = os.path.join(ROOT, 'sample_faces', 'Vedant Goyal', 'Vedant.jpeg')


class FakeDB:
    """Keeps Face_Embeddings rows in a list; answers the three queries register_person runs."""

    def __init__(self):
        self.rows = []

    def execute_query(self, query, params=None, fetch=False, fetch_one=False):
        if query.startswith('SELECT Name FROM User'):
            return {'Name': 'Vedant Goyal'}
        if query.startswith('SELECT Face_Encoding'):
            return [{'Face_Encoding': enc} for uid, enc, _ in self.rows if uid == params[0]]
        if query.startswith('INSERT INTO Face_Embeddings'):
            self.rows.append(params)
            return len(self.rows)
        raise AssertionError(f'unexpected query: {query}')


def registration():
    reg = FaceRegistration.__new__(FaceRegistration)  # skip __init__, which opens the MySQL pool
    reg.db = FakeDB()
    return reg


def test_same_photo_is_registered_once_even_under_another_path():
    reg = registration()
    assert reg.register_person(21, PHOTO) == 1
    for path in (PHOTO, os.path.relpath(PHOTO)):
        with pytest.raises(RegistrationError, match='already registered') as err:
            reg.register_person(21, path)
        assert err.value.status == 409
    assert len(reg.db.rows) == 1


def test_same_photo_can_still_be_registered_for_a_different_user():
    reg = registration()
    assert reg.register_person(21, PHOTO) == 1
    assert reg.register_person(20, PHOTO) == 1
    assert len(reg.db.rows) == 2


def test_missing_file_explains_the_path_problem():
    with pytest.raises(RegistrationError, match='File not found') as err:
        registration().register_person(21, '/Users/someone/elsewhere/photo.jpg')
    assert err.value.status == 400
    assert 'sample_faces/<Name>/<file>' in str(err.value)
