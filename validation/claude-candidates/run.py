"""Run saved recipes through the public API; no custom rendering logic."""
import argparse
import json
from pathlib import Path
import time
import traceback

from ldraw_xray import Session

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', nargs='*', help='Optional exact case ids')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    session = Session()
    results = []
    for case in json.loads((HERE / 'cases.json').read_text()):
        if args.cases and case['id'] not in args.cases:
            continue
        output = HERE / 'renders' / case['id']
        if (output / 'manifest.json').exists() and not args.force:
            print('EXISTS', case['id'], flush=True)
            continue
        start = time.monotonic()
        print('START', case['id'], flush=True)
        try:
            manifest = session.board(HERE / case['recipe'], output=output,
                                     keep_intermediates=True, force=args.force)
            result = dict(id=case['id'], status='rendered', seconds=round(time.monotonic()-start, 2),
                          panels=len(manifest['panels']), duplicates=manifest['mosaic']['duplicates'],
                          notes=[p['notes'] for p in manifest['panels']],
                          warnings=[p['warnings'] for p in manifest['panels']])
        except Exception as error:
            result = dict(id=case['id'], status='failed', error=str(error), traceback=traceback.format_exc())
        results.append(result)
        evidence = HERE / 'evidence'
        evidence.mkdir(exist_ok=True)
        (evidence / (case['id'] + '.json')).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
    return int(any(r['status'] == 'failed' for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
