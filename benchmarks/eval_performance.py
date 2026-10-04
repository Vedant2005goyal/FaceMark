"""Speed benchmark of the live recognition pipeline used in attendance.MarkAttendance.recognize_user.

Measures, per webcam frame: face detection, encoding and matching time at several downscale
factors, HOG vs CNN detection, the effect of frame skipping, and how matching cost grows with
the number of enrolled students.

Frames are synthetic 1280x720 "webcam" frames with LFW faces pasted in (face ~220 px wide),
unless --webcam is given, in which case real frames are captured from camera 0.

Usage:  python benchmarks/eval_performance.py [--webcam]
Output: benchmarks/results/performance.json
"""
import argparse
import json
import platform
import random
import statistics
import sys
import time
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import face_recognition  # noqa: E402
from face_matching import FaceMatcher, ConfirmationTracker, encode_largest_face  # noqa: E402
from benchmarks.eval_recognition import lfw_dir, RESULTS  # noqa: E402

FRAME_W, FRAME_H = 1280, 720


def ms(samples):
    return {'median_ms': round(1000 * statistics.median(samples), 2),
            'p95_ms': round(1000 * float(np.percentile(samples, 95)), 2)}


def synthetic_frames(photos, n_frames, faces_per_frame, rng):
    frames = []
    for _ in range(n_frames):
        canvas = np.full((FRAME_H, FRAME_W, 3), 90, dtype=np.uint8)
        slots = rng.sample(range(FRAME_W // 500), faces_per_frame) if faces_per_frame > 1 else [rng.randrange(FRAME_W // 500)]
        for slot in slots:
            face = cv.imread(rng.choice(photos))
            face = cv.resize(face, (500, 500), interpolation=cv.INTER_CUBIC)
            x, y = slot * 500 + rng.randrange(0, FRAME_W // (FRAME_W // 500) - 500 + 1), rng.randrange(0, FRAME_H - 500)
            canvas[y:y + 500, x:x + 500] = face
        frames.append((canvas, faces_per_frame))
    return frames


def webcam_frames(n_frames):
    cap = cv.VideoCapture(0)
    frames = []
    while len(frames) < n_frames:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append((frame, 1))
    cap.release()
    if not frames:
        sys.exit("Could not read from webcam 0")
    return frames


def run_pipeline(frames, matcher, scale, model):
    """One pass of the per-frame work in recognize_user, timed stage by stage."""
    detect, encode, match, total = [], [], [], []
    found = expected = 0
    for frame, n_faces in frames:
        t0 = time.perf_counter()
        small = cv.resize(frame, (0, 0), fx=scale, fy=scale) if scale != 1 else frame
        rgb = cv.cvtColor(small, cv.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model=model)
        t1 = time.perf_counter()
        encodings = face_recognition.face_encodings(rgb, locations)
        t2 = time.perf_counter()
        for enc in encodings:
            matcher.match(enc)
        t3 = time.perf_counter()
        detect.append(t1 - t0); encode.append(t2 - t1); match.append(t3 - t2); total.append(t3 - t0)
        found += min(len(locations), n_faces)
        expected += n_faces
    return {
        'detect': ms(detect), 'encode': ms(encode), 'match': ms(match), 'total': ms(total),
        'fps': round(1 / statistics.median(total), 2),
        'detection_rate': round(found / expected, 4),
    }


def frame_skip_loop(frames, matcher, scale, skip, confirm):
    """Frames handled per second by the camera loop when recognition runs on every `skip`th frame."""
    tracker = ConfirmationTracker(confirm)
    start = time.perf_counter()
    for i, (frame, _) in enumerate(frames):
        if i % skip == 0:
            small = cv.resize(frame, (0, 0), fx=scale, fy=scale)
            rgb = cv.cvtColor(small, cv.COLOR_BGR2RGB)
            locations = face_recognition.face_locations(rgb)
            labels = [matcher.match(e)[0] for e in face_recognition.face_encodings(rgb, locations)]
            tracker.update(l for l in labels if l is not None)
    return round(len(frames) / (time.perf_counter() - start), 2)


def matching_scalability(base_encodings, sizes, rng_np):
    out = {}
    queries = base_encodings[:50]
    for n in sizes:
        matcher = FaceMatcher(tolerance=0.55)
        for i in range(n):
            matcher.add(i, base_encodings[i % len(base_encodings)] + rng_np.normal(0, 0.02, 128))
        matcher.nearest(queries[0])  # build the gallery matrix outside the timed loop
        samples = []
        for q in queries:
            t0 = time.perf_counter()
            matcher.match(q)
            samples.append(time.perf_counter() - t0)
        out[n] = {'median_ms': round(1000 * statistics.median(samples), 4)}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--webcam', action='store_true', help='use real frames from camera 0')
    ap.add_argument('--frames', type=int, default=40)
    ap.add_argument('--gallery', type=int, default=60, help='students enrolled during the speed test')
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()
    rng, rng_np = random.Random(args.seed), np.random.default_rng(args.seed)

    root = lfw_dir()
    people = sorted(d for d in root.iterdir() if d.is_dir() and len(list(d.glob('*.jpg'))) >= 2)
    rng.shuffle(people)
    photos = [str(next(iter(sorted(p.glob('*.jpg'))))) for p in people[:400]]

    print(f"Enrolling {args.gallery} identities...")
    matcher, base = FaceMatcher(tolerance=0.55), []
    for path in photos:
        if len(base) >= args.gallery:
            break
        enc, _ = encode_largest_face(face_recognition.load_image_file(path))
        if enc is not None:
            matcher.add(path, enc)
            base.append(enc)

    probe_photos = photos[args.gallery:]
    one_face = webcam_frames(args.frames) if args.webcam else synthetic_frames(probe_photos, args.frames, 1, rng)
    two_faces = None if args.webcam else synthetic_frames(probe_photos, args.frames // 2, 2, rng)

    results = {
        'machine': {'platform': platform.platform(), 'processor': platform.processor() or platform.machine(),
                    'python': platform.python_version()},
        'frames': {'source': 'webcam' if args.webcam else 'synthetic 1280x720, LFW faces ~220px',
                   'count': len(one_face), 'gallery_size': len(matcher)},
        'hog_by_scale': {}, 'frame_skip': {}, 'matching_scalability': {},
    }

    for scale in (1.0, 0.5, 0.25):
        print(f"HOG pipeline at scale {scale}...")
        results['hog_by_scale'][str(scale)] = run_pipeline(one_face, matcher, scale, 'hog')
    print("CNN detector at scale 0.25 (CPU)...")
    results['cnn_scale_0.25'] = run_pipeline(one_face[:10], matcher, 0.25, 'cnn')
    if two_faces:
        print("Two faces per frame at scale 0.25...")
        results['two_faces_scale_0.25'] = run_pipeline(two_faces, matcher, 0.25, 'hog')

    for skip in (1, 2, 3):
        print(f"Camera loop with FRAME_SKIP={skip}...")
        results['frame_skip'][skip] = {'loop_fps': frame_skip_loop(one_face, matcher, 0.25, skip, 3)}

    print("Matching cost vs gallery size...")
    results['matching_scalability'] = matching_scalability(np.array(base), (24, 100, 1_000, 10_000, 100_000), rng_np)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / 'performance.json').write_text(json.dumps(results, indent=2))

    print(f"\n{'pipeline':<22} {'detect':>9} {'encode':>9} {'match':>8} {'total':>9} {'FPS':>6} {'detected':>9}")
    rows = [(f'HOG scale {s}', r) for s, r in results['hog_by_scale'].items()] + [('CNN scale 0.25', results['cnn_scale_0.25'])]
    if 'two_faces_scale_0.25' in results:
        rows.append(('HOG 0.25, 2 faces', results['two_faces_scale_0.25']))
    for name, r in rows:
        print(f"{name:<22} {r['detect']['median_ms']:7.1f}ms {r['encode']['median_ms']:7.1f}ms "
              f"{r['match']['median_ms']:6.2f}ms {r['total']['median_ms']:7.1f}ms {r['fps']:6.1f} {100 * r['detection_rate']:8.1f}%")
    print("\nCamera loop FPS by FRAME_SKIP:", {k: v['loop_fps'] for k, v in results['frame_skip'].items()})
    print("Match time vs gallery size (ms):", {k: v['median_ms'] for k, v in results['matching_scalability'].items()})
    print(f"\nWrote {RESULTS / 'performance.json'}")


if __name__ == '__main__':
    main()
