"""Enrol faces: turn a photo into a 128-d embedding and store it in Face_Embeddings.

Run directly to bulk-register sample_faces/<User.Name>/*.jpg.
"""
import json
import os

import face_recognition
import numpy as np

from config import Config
from database import DatabaseManager
from face_matching import encode_largest_face


class RegistrationError(Exception):
    """Why a photo was not registered. `status` is the HTTP code the API answers with."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class FaceRegistration:
    def __init__(self):
        self.db = DatabaseManager()

    def get_user_id_by_name(self, name):
        row = self.db.execute_query("SELECT User_ID FROM User WHERE Name = %s", (name,), fetch_one=True)
        return row['User_ID'] if row else None

    def stored_encodings(self, user_id):
        rows = self.db.execute_query(
            "SELECT Face_Encoding FROM Face_Embeddings WHERE User_ID = %s", (user_id,), fetch=True)
        return [np.array(json.loads(row['Face_Encoding'])) for row in rows]

    def register_person(self, user_id, image_path) -> int:
        """Store one photo's embedding for a user and return how many photos they now have.
        Up to MAX_EMBEDDINGS_PER_USER photos per person are kept; several photos make
        recognition robust to lighting and angle. Raises RegistrationError with the reason
        otherwise; a photo that is already registered is refused, so re-runs are safe."""
        if not os.path.exists(image_path):
            raise RegistrationError(
                f"File not found: {image_path} (the path must exist where the API runs; "
                f"in Docker use sample_faces/<Name>/<file>)")
        user = self.db.execute_query("SELECT Name FROM User WHERE User_ID = %s", (user_id,), fetch_one=True)
        if not user:
            raise RegistrationError(f"User {user_id} not found", status=404)

        image = face_recognition.load_image_file(image_path)
        encoding, _ = encode_largest_face(image, model=Config.FACE_DETECTION_MODEL)
        if encoding is None:
            raise RegistrationError(f"No face detected in {image_path}")

        # The same photo always gives the exact same embedding, whatever its file name or path
        existing = self.stored_encodings(user_id)
        if any(np.allclose(encoding, stored) for stored in existing):
            raise RegistrationError(f"{user['Name']}: {image_path} is already registered", status=409)
        if len(existing) >= Config.MAX_EMBEDDINGS_PER_USER:
            raise RegistrationError(
                f"{user['Name']} already has {len(existing)} photos (max {Config.MAX_EMBEDDINGS_PER_USER})",
                status=409)

        self.db.execute_query(
            "INSERT INTO Face_Embeddings (User_ID, Face_Encoding, Photo_Path) VALUES (%s, %s, %s)",
            (user_id, json.dumps(encoding.tolist()), image_path))
        print(f"✓ {user['Name']} registered ({len(existing) + 1} photo(s))")
        return len(existing) + 1


if __name__ == "__main__":
    registration = FaceRegistration()
    dataset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample_faces')
    # One folder per person, named exactly as their User.Name
    for person in sorted(os.listdir(dataset_dir)):
        person_dir = os.path.join(dataset_dir, person)
        if person.startswith('.') or not os.path.isdir(person_dir):
            continue
        user_id = registration.get_user_id_by_name(person)
        if user_id is None:
            print(f"Skipping '{person}': no User row with that name")
            continue
        for file_name in sorted(os.listdir(person_dir)):
            if file_name.lower().endswith(('.png', '.jpeg', '.jpg')):
                try:
                    registration.register_person(user_id, os.path.join(person_dir, file_name))
                except RegistrationError as e:
                    print(f"- skipped: {e}")
