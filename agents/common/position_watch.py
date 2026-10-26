"""Deterministic execution of explicit manager-approved monitoring parameters."""
from datetime import datetime,timezone

from agents.manager.market_view import market_view


def utc(value):
    at=datetime.fromisoformat(value.replace('Z','+00:00'))
    if at.tzinfo is None:raise ValueError('monitor timestamps must be timezone-aware')
    return at


def position_watch(plan,bars,positions,orders,now=None,next_review=None):
    now=now or datetime.now(timezone.utc)
    pid=plan.get('position_id')
    if not any(p['id']==pid for p in positions):
        return {'action':'done','reason':'position no longer open'}
    config=plan.get('monitoring')
    if not config or not config.get('approved'):
        return {'action':'wait','reason':'no approved deterministic monitoring configuration'}
    if plan.get('expiry') and now>=utc(plan['expiry']):
        return {'action':'close','reason':'approved plan expired','position_id':pid}
    protection=plan['protective_orders']
    stop=any(o.get('position_id')==pid and o.get('order_type')=='stop' and o.get('reduce_only')
             and o.get('status') in ('open','untriggered')
             and o.get('trigger_price')==protection['stop_mark'] for o in orders)
    if not stop:
        return {'action':'restore_stop','reason':'approved protective stop absent','position_id':pid}
    due=utc(next_review or plan['next_review'])
    if now<due:return {'action':'wait','reason':'not yet due'}
    view=market_view(bars,now)
    if not view.get('available') or view['stale']:
        return {'action':'wait','reason':'review awaits fresh completed candles'}
    hs=view['horizons']
    if any(not hs[str(h)].get('available') or hs[str(h)]['anchor_gap_minutes'] for h in (1,4)):
        return {'action':'wait','reason':'review awaits exact 1h/4h anchors'}
    r1,r4=hs['1']['change_bps'],hs['4']['change_bps']
    bad=r4<=config['invalidation_4h_bps'] and r1<config['invalidation_1h_bps']
    return {'action':'close' if bad else 'review','position_id':pid,
            'reason':'approved directional invalidation' if bad else 'thesis condition not invalidated',
            'return_1h_bps':r1,'return_4h_bps':r4,'cutoff':view['latest_close_available_at'],
            'next_review':datetime.fromtimestamp(now.timestamp()+config['interval_s'],timezone.utc).isoformat()}
