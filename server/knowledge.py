"""Append-only, attributed collective memory and development-history retrieval."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading

from agents.common.experience import build_atlas, state_features, retrieve
from . import fees
from .evaluator import service
from .market import PRODUCT
from .store import now

_LOCK = threading.Lock()


def append(store, who: dict, entry: dict) -> dict:
    """No agent can rewrite another's contribution or declare a vote verified."""
    if who['role'] not in ('boss','manager','trader'):
        raise ValueError('not a knowledge contributor')
    cutoff = datetime.fromisoformat(entry['information_cutoff'].replace('Z','+00:00'))
    if cutoff.tzinfo is None or cutoff > datetime.now(timezone.utc):
        raise ValueError('information_cutoff must be a timezone-aware past time')
    for parent in entry.get('parent_ids',[]):
        parents=store.q("SELECT ts,kind,payload FROM events WHERE id=? AND kind IN ('knowledge','close')",(parent,))
        if not parents:
            raise ValueError(f'unknown knowledge parent {parent}')
        p=parents[0]
        parent_cutoff=json.loads(p['payload']).get('information_cutoff',p['ts'])
        if datetime.fromisoformat(parent_cutoff.replace('Z','+00:00'))>cutoff:
            raise ValueError('parent evidence is later than information_cutoff')
    return store.emit(who['id'],'knowledge',{**entry,'provenance':'agent_submitted',
                      'information_cutoff':cutoff.astimezone(timezone.utc).isoformat()})


def listing(store, topic: str | None = None, limit: int = 20) -> list[dict]:
    if topic:
        rows = store.q("SELECT * FROM events WHERE (kind='knowledge' AND json_extract(payload,'$.topic')=?) "
                       "OR (kind='close' AND ?='paper-execution') ORDER BY id DESC LIMIT ?",
                       (topic,topic,max(1,min(limit,100))))
    else:
        rows = store.q("SELECT * FROM events WHERE kind IN ('knowledge','close') ORDER BY id DESC LIMIT ?",
                       (max(1,min(limit,100)),))
    for row in rows:
        row['payload'] = json.loads(row['payload'])
        if row['kind']=='close':
            p=row['payload']
            row['payload']={'topic':'paper-execution','perspective':'execution','kind':'result',
                'claim':f"Position {p['position']}: net {p['pnl']} USD / {p['pnl_bps']} bps; "
                        f"fees {p['fees']} USD, funding {p.get('funding',0)} USD; exit {p['reason']}.",
                'information_cutoff':row['ts'],'evidence':[f"position:{p['position']}",f"close-event:{row['id']}"],
                'parent_ids':[], 'limitations':'One simulated execution outcome; not evidence of a stable edge.',
                'provenance':'office_measured','measured':p}
    return rows


def experience(market) -> dict:
    """Read only train_file; never heldout_file or the evaluation detail stream."""
    now_utc = datetime.now(timezone.utc)
    boundary = now_utc-timedelta(days=service.HELDOUT_DAYS+service.GAP_DAYS)
    with _LOCK:
        source = service.train_file(market)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        # Include data hash and cost regime so a replacement cannot reuse old episodes.
        path = service.CACHE/f'{PRODUCT}_experience_v1_{digest[:16]}_{fees.TAKER}.json'
        if not path.exists():
            atlas = build_atlas(json.loads(source.read_text()),int(boundary.timestamp()),fees.TAKER)
            atlas['source_sha256'] = digest
            atlas['source_file'] = source.name
            atlas['generated_at_utc'] = now()
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(atlas));temp.replace(path)
        atlas = json.loads(path.read_text())
        if atlas['last_bar']:
            from agents.common.experience import epoch
            if epoch(atlas['last_bar'])+60 > int(boundary.timestamp()):
                raise ValueError('cached atlas exceeds current development boundary')
    current = state_features(market.bars(PRODUCT,482),int(now_utc.timestamp()))
    return retrieve(atlas,current)
