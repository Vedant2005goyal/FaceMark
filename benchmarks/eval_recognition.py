"""Recognition accuracy benchmark on LFW (Labeled Faces in the Wild).

Simulates the attendance setting as open-set identification:
  * identities with >= --min-images photos are split into ENROLLED "students" and held-out
    IMPOSTORS (people who walk past the camera but are not in the class)
  * each student is enrolled with k photos (k = 1, 3, 5), mirroring register_faces.register_person
  * up to --max-probes other photos of every identity are used as "camera" probes
  * probes are matched with the same FaceMatcher the app uses (face_matching.py)

Usage:  python benchmarks/eval_recognition.py            (first run downloads LFW, ~190 MB)
Output: benchmarks/results/recognition.json and recognition.png
"""
import argparse
import json
import os
import pickle
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from face_matching import FaceMatcher, encode_largest_face  # noqa: E402

CACHE = ROOT / 'benchmarks' / 'cache'
RESULTS = ROOT / 'benchmarks' / 'results'
THRESHOLDS = np.round(np.arange(0.30, 0.701, 0.01), 2)
APP_TOLERANCE = 0.55  # the value hardcoded in the original version of the app
ENROLL_SIZES = (1, 3, 5)


LFW_PARQUET_URL = 'https://huggingface.co/datasets/bitmind/lfw/resolve/main/data/train-00000-of-00001.parquet'


def lfw_dir() -> Path:
    """LFW as <cache>/lfw/<Person_Name>/<Person_Name>_0001.jpg, downloaded on first use.

    scikit-learn's fetch_lfw_people mirror (figshare) answers 403, so this uses a Hugging Face
    copy of the original 13,233-image release (250x250 RGB, standard LFW filenames)."""
    out = CACHE / 'lfw'
    if out.exists() and any(out.iterdir()):
        return out
    parquet = CACHE / 'lfw.parquet'
    if not parquet.exists():
        import urllib.request
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"Downloading LFW (~190 MB) from {LFW_PARQUET_URL} ...")
        urllib.request.urlretrieve(LFW_PARQUET_URL, parquet)
    import pyarrow.parquet as pq
    table = pq.read_table(parquet)
    for row in table.to_pylist():
        name = row['filename']
        person_dir = out / name[:-len('_0001.jpg')]
        person_dir.mkdir(parents=True, exist_ok=True)
        (person_dir / name).write_bytes(row['image']['bytes'])
    print(f"Extracted {table.num_rows} images to {out}")
    return out


def _encode(path: str):
    import face_recognition
    encoding, _ = encode_largest_face(face_recognition.load_image_file(path))
    return path, encoding


def encode_all(paths, workers):
    cache_file = CACHE / 'lfw_encodings.pkl'
    cache = pickle.loads(cache_file.read_bytes()) if cache_file.exists() else {}
    todo = [p for p in paths if p not in cache]
    if todo:
        print(f"Encoding {len(todo)} images with {workers} workers ({len(cache)} cached)...")
        start = time.time()
        with Pool(workers) as pool:
            for i, (path, enc) in enumerate(pool.imap_unordered(_encode, todo, chunksize=8), 1):
                cache[path] = enc
                if i % 250 == 0:
                    print(f"  {i}/{len(todo)}  ({time.time() - start:.0f}s)")
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(pickle.dumps(cache))
    return {p: cache[p] for p in paths}


def evaluate(gallery, genuine, impostor, strategy):
    """gallery: {label: [enc]}, genuine: [(label, enc)], impostor: [(identity, enc)].
    Returns nearest-match (label, distance) arrays so any threshold can be applied afterwards."""
    matcher = FaceMatcher(tolerance=1.0, strategy=strategy)
    for label, encs in gallery.items():
        for enc in encs:
            matcher.add(label, enc)
    gen = [(true, *matcher.nearest(enc)) for true, enc in genuine]
    imp = [(ident, *matcher.nearest(enc)) for ident, enc in impostor]
    return gen, imp


def rates_at(gen, imp, t):
    n_gen, n_imp = len(gen), len(imp)
    correct = sum(1 for true, lab, d in gen if d <= t and lab == true)
    misid = sum(1 for true, lab, d in gen if d <= t and lab != true)
    false_accept = sum(1 for _, _, d in imp if d <= t)
    return {
        'threshold': float(t),
        'identification_rate': correct / n_gen,           # student recognised as themselves
        'false_reject_rate': 1 - correct / n_gen,          # student not marked (or marked as someone else)
        'misidentification_rate': misid / n_gen,           # student marked as a *different* student
        'false_accept_rate': false_accept / n_imp,         # stranger marked as some student
        'overall_accuracy': (correct + n_imp - false_accept) / (n_gen + n_imp),
    }


def summarise(gen, imp):
    sweep = [rates_at(gen, imp, t) for t in THRESHOLDS]
    eer_point = min(sweep, key=lambda r: abs(r['false_reject_rate'] - r['false_accept_rate']))
    within_1pct = [r for r in sweep if r['false_accept_rate'] <= 0.01]
    best = max(within_1pct, key=lambda r: r['identification_rate']) if within_1pct else eer_point
    return {
        'rank1_accuracy': sum(1 for true, lab, _ in gen if lab == true) / len(gen),  # closed-set, no threshold
        'at_app_tolerance': rates_at(gen, imp, APP_TOLERANCE),
        'eer': (eer_point['false_reject_rate'] + eer_point['false_accept_rate']) / 2,
        'eer_threshold': eer_point['threshold'],
        'best_threshold_far_le_1pct': best,
        'sweep': sweep,
    }


def confirmation_study(gen, imp, frames_per_probe_group, t):
    """Multi-frame confirmation: a student is only marked when M probes in a row all match the
    same identity. Probes here are independent photos, so this is an upper bound on the benefit
    for a webcam (consecutive frames are correlated)."""
    def groups(rows, m):
        by_id = {}
        for row in rows:
            by_id.setdefault(row[0], []).append(row)
        for rows_ in by_id.values():
            for i in range(0, len(rows_) - m + 1, m):
                yield rows_[i:i + m]

    out = {}
    for m in frames_per_probe_group:
        g = list(groups(gen, m))
        i = list(groups(imp, m))
        confirmed = lambda grp: all(d <= t for _, _, d in grp) and len({lab for _, lab, _ in grp}) == 1
        correct = sum(1 for grp in g if confirmed(grp) and grp[0][1] == grp[0][0])
        misid = sum(1 for grp in g if confirmed(grp) and grp[0][1] != grp[0][0])
        fa = sum(1 for grp in i if confirmed(grp))
        out[m] = {
            'identification_rate': correct / len(g),
            'misidentification_rate': misid / len(g),
            'false_accept_rate': fa / len(i),
            'genuine_sequences': len(g),
            'impostor_sequences': len(i),
        }
    return out


def plot(results, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    best_key = results['recommended']['config']
    for key, style in (('k1_min', '--'), (best_key, '-')):
        sweep = results['configs'][key]['sweep']
        t = [r['threshold'] for r in sweep]
        label = '1 photo' if key == 'k1_min' else f"{key[1]} photos, {key.split('_')[1]}"
        ax.plot(t, [100 * r['false_accept_rate'] for r in sweep], style, color='tab:red', label=f'False accept ({label})')
        ax.plot(t, [100 * r['false_reject_rate'] for r in sweep], style, color='tab:blue', label=f'False reject ({label})')
    ax.axvline(APP_TOLERANCE, color='gray', linestyle=':', label=f'Original tolerance {APP_TOLERANCE}')
    ax.axvline(results['recommended']['threshold'], color='black', linestyle='-.',
               label=f"Recommended {results['recommended']['threshold']}")
    ax.set_xlabel('Distance threshold (tolerance)')
    ax.set_ylabel('Error rate (%)')
    ax.set_title('FaceMark on LFW: error rates vs threshold')
    ax.set_ylim(0, 40)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--min-images', type=int, default=10, help='photos an identity needs to be used')
    ap.add_argument('--max-probes', type=int, default=9, help='probe photos per identity')
    ap.add_argument('--impostor-fraction', type=float, default=0.25, help='identities held out as strangers')
    ap.add_argument('--extra-impostors', type=int, default=1000,
                    help='additional stranger identities sampled from people with 2..min-images-1 photos')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    root = lfw_dir()
    counts = {d.name: len(list(d.glob('*.jpg'))) for d in root.iterdir() if d.is_dir()}
    eligible = sorted(p for p, n in counts.items() if n >= args.min_images)
    rng.shuffle(eligible)
    n_imp = int(len(eligible) * args.impostor_fraction)
    enrolled_ids = sorted(eligible[n_imp:])
    small = sorted(p for p, n in counts.items() if 2 <= n < args.min_images)
    impostor_ids = sorted(eligible[:n_imp]) + sorted(rng.sample(small, min(args.extra_impostors, len(small))))

    # Pick photos up front (max enrolment + probes per identity) so only those get encoded
    k_max = max(ENROLL_SIZES)
    chosen = {}
    for p in enrolled_ids + impostor_ids:
        photos = sorted(str(f) for f in (root / p).glob('*.jpg'))
        rng.shuffle(photos)
        chosen[p] = photos[:k_max + args.max_probes + 3]  # a few spares for detection failures
    all_paths = [path for paths in chosen.values() for path in paths]
    encodings = encode_all(all_paths, args.workers)
    failed = sum(1 for e in encodings.values() if e is None)

    usable = {p: [encodings[x] for x in chosen[p] if encodings[x] is not None] for p in chosen}
    enrolled_ids = [p for p in enrolled_ids if len(usable[p]) >= k_max + 1]
    impostor = [(p, enc) for p in impostor_ids for enc in usable[p][:args.max_probes]]
    genuine = [(p, enc) for p in enrolled_ids for enc in usable[p][k_max:k_max + args.max_probes]]

    results = {
        'dataset': {
            'name': 'LFW (original 13,233-image release)',
            'enrolled_identities': len(enrolled_ids),
            'impostor_identities': len(impostor_ids),
            'genuine_probes': len(genuine),
            'impostor_probes': len(impostor),
            'images_encoded': len(all_paths),
            'face_not_detected_rate': failed / len(all_paths),
            'seed': args.seed,
        },
        'configs': {},
    }
    raw = {}
    for k in ENROLL_SIZES:
        for strategy in (('min',) if k == 1 else ('min', 'mean')):
            gallery = {p: usable[p][:k] for p in enrolled_ids}
            gen, imp = evaluate(gallery, genuine, impostor, strategy)
            key = f'k{k}_{strategy}'
            raw[key] = (gen, imp)
            results['configs'][key] = summarise(gen, imp)

    # Recommend: config + threshold with the best identification rate while FAR <= 1%
    best_key = max(results['configs'], key=lambda c: results['configs'][c]['best_threshold_far_le_1pct']['identification_rate'])
    best = results['configs'][best_key]['best_threshold_far_le_1pct']
    results['recommended'] = {'config': best_key, **best}
    gen, imp = raw[best_key]
    results['multi_frame_confirmation'] = confirmation_study(gen, imp, (1, 2, 3), best['threshold'])

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / 'recognition.json').write_text(json.dumps(results, indent=2))
    plot(results, RESULTS / 'recognition.png')

    d = results['dataset']
    print(f"\nLFW: {d['enrolled_identities']} enrolled, {d['impostor_identities']} impostor identities, "
          f"{d['genuine_probes']} genuine + {d['impostor_probes']} impostor probes, "
          f"no face detected in {100 * d['face_not_detected_rate']:.1f}% of images\n")
    print(f"{'config':<8} {'rank-1':>7} | @{APP_TOLERANCE}: {'ident':>6} {'FAR':>6} {'misID':>6} {'acc':>6} | "
          f"{'EER':>5} @t | best t (FAR<=1%): ident")
    for key, r in results['configs'].items():
        a, b = r['at_app_tolerance'], r['best_threshold_far_le_1pct']
        print(f"{key:<8} {100 * r['rank1_accuracy']:6.2f}% | {100 * a['identification_rate']:11.2f}% "
              f"{100 * a['false_accept_rate']:5.2f}% {100 * a['misidentification_rate']:5.2f}% "
              f"{100 * a['overall_accuracy']:5.2f}% | {100 * r['eer']:4.2f}% @{r['eer_threshold']:.2f} | "
              f"{b['threshold']:.2f}: {100 * b['identification_rate']:.2f}% (FAR {100 * b['false_accept_rate']:.2f}%)")
    print(f"\nRecommended: {best_key} at threshold {best['threshold']}")
    print("Multi-frame confirmation at that threshold:")
    for m, r in results['multi_frame_confirmation'].items():
        print(f"  M={m}: ident {100 * r['identification_rate']:.2f}%  FAR {100 * r['false_accept_rate']:.2f}%  "
              f"misID {100 * r['misidentification_rate']:.2f}%  ({r['impostor_sequences']} impostor sequences)")
    print(f"\nWrote {RESULTS / 'recognition.json'} and {RESULTS / 'recognition.png'}")


if __name__ == '__main__':
    main()
