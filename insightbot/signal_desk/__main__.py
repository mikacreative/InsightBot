import argparse
import json
import os
import uuid
from pathlib import Path

from .core import Desk


def main():
    parser = argparse.ArgumentParser(description='Signal Desk isolated test workflow')
    parser.add_argument('--state-dir', default=os.environ.get('SIGNAL_DESK_STATE_DIR', 'data/signal-desk'))
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--input', required=True)
    run.add_argument('--id', default=None)
    run.add_argument('--mode', choices=['demo', 'replay', 'live'], default='demo')
    status = sub.add_parser('status'); status.add_argument('id')
    review = sub.add_parser('review'); review.add_argument('id'); review.add_argument('--decision', choices=['approve','reject'], required=True)
    review.add_argument('--reviewer', required=True); review.add_argument('--note', default='')
    serve = sub.add_parser('serve'); serve.add_argument('--host', default='127.0.0.1'); serve.add_argument('--port', type=int, default=18876)
    search = sub.add_parser('search'); search.add_argument('--keyword', required=True); search.add_argument('--output', required=True); search.add_argument('--note-time', choices=['ONE_DAY','ONE_WEEK','HALF_YEAR'])
    detail = sub.add_parser('detail'); detail.add_argument('--note-id', required=True); detail.add_argument('--output', required=True)
    collect = sub.add_parser('collect'); collect.add_argument('--keyword', required=True); collect.add_argument('--brand', required=True); collect.add_argument('--question', required=True); collect.add_argument('--output', required=True); collect.add_argument('--note-time', choices=['ONE_DAY','ONE_WEEK','HALF_YEAR'])
    args = parser.parse_args()
    if args.command in ('search','detail','collect'):
        from .providers import justone_search, justone_note_detail, search_to_input
        # Reserve output before spending, preventing overwrite/repeated paid calls.
        with Path(args.output).open('x', encoding='utf-8') as output:
            result = justone_search(args.keyword, args.note_time) if args.command in ('search','collect') else justone_note_detail(args.note_id)
            if args.command == 'collect':
                result = search_to_input(result, args.brand, args.question)
            json.dump(result, output, ensure_ascii=False, indent=2)
        print('Saved workflow input.' if args.command == 'collect' else 'Saved provider response. Normalize evidence before run; no automatic retry.')
        return
    if args.command == 'serve':
        from .web import serve
        serve(args.state_dir, args.host, args.port)
        return
    desk = Desk(args.state_dir)
    if args.command == 'run':
        payload = json.loads(Path(args.input).read_text())
        run_id = args.id or uuid.uuid4().hex
        result = desk.start(run_id, payload['brief'], payload['evidence'], args.mode, payload.get('replay_cards', []), payload.get('collection', {}))
        result['run_id'] = run_id
    elif args.command == 'status':
        result = desk.status(args.id)
    else:
        result = desk.resume(args.id, args.decision, args.reviewer, args.note)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
