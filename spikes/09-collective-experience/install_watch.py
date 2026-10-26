"""Run in the shared REPL: execute position #4's already-approved monitoring plan."""
assert mgr_market_plan.get('position_id') == 4, 'Plan changed; do not overwrite it'
assert mgr_market_plan['protective_orders']['stop_mark'] == 82920
assert mgr_market_plan['size_risk_limits']['planned_loss_cap_usd_including_fees'] == .5
if 'mgr_previous_should_wake' not in globals():
    mgr_previous_should_wake = globals().get('should_wake')

mgr_market_plan['monitoring'] = {'approved':True,'invalidation_4h_bps':-20.,
                                'invalidation_1h_bps':0.,'interval_s':900}
mgr_collective_watch_state = {'events':[]}


def should_wake(bars):
    from datetime import datetime,timezone
    from agents.common.position_watch import position_watch
    from agents.common.office_client import Office
    _now = datetime.now(timezone.utc)
    _plan = globals().get('mgr_market_plan',{})
    _state = globals()['mgr_collective_watch_state']
    _token = (_plan.get('position_id'),_plan.get('as_of'),repr(_plan.get('monitoring')))
    if _state.get('token') != _token:
        _state['token'] = _token
        _state['next_review'] = _plan.get('next_review')
    _signal = position_watch(_plan,bars,globals().get('positions_open',[]),
                             globals().get('my_orders',[]),_now,_state.get('next_review'))
    _action = _signal['action']
    if _action in ('wait','done'):
        return False
    if _action == 'review':
        _state['next_review'] = _signal['next_review']
    elif _action == 'restore_stop':
        _p = _plan['protective_orders']
        _result = place_order('close',position_id=_plan['position_id'],order_type='stop',
                             trigger_price=_p['stop_mark'],trigger_signal='mark',reduce_only=True,
                             post_only=False,oco=_p['oco'])
        # Verify the office state, rather than trusting a possibly stale REPL return object.
        _client = Office()
        try:
            _orders = _client.get('/orders',employee=me['id'],open='true')
            _positions = _client.get('/positions',employee=me['id'],open='true')
        finally:
            _client.http.close()
        _after = position_watch(_plan,bars,_positions,_orders,_now,_state.get('next_review'))
        if _after['action'] == 'restore_stop':
            _result = close_position(_plan['position_id'])
            _signal['fallback'] = 'close requested because approved stop could not be restored'
    elif _action == 'close':
        _result = close_position(_plan['position_id'])
        _client = Office()
        try:
            _remaining = _client.get('/positions',employee=me['id'],open='true')
        finally:
            _client.http.close()
        _signal['close_confirmed'] = not any(p['id']==_plan['position_id'] for p in _remaining)
    _state['events'].append({'observed_at':_now.isoformat(),**_signal})
    _state['events'] = _state['events'][-100:]
    return True


mgr_plan_journal.append({'ts':office_time,'reason':'Implemented the approved 15m review/invalidation as deterministic overnight monitoring; old watcher referenced position #2. Existing risk, stop, take-profit and expiry preserved.',
                         'new':dict(mgr_market_plan),'source':'spikes/09-collective-experience/install_watch.py',
                         'collective_experiment_entry':3985})
print({'position':mgr_market_plan['position_id'],'monitoring':mgr_market_plan['monitoring'],
       'next_review':mgr_market_plan['next_review'],'old_watcher_preserved':callable(mgr_previous_should_wake),
       'model_calls':0})
