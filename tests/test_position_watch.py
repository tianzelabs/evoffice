from datetime import datetime,timedelta,timezone

from agents.common.position_watch import position_watch

T0=datetime(2020,1,1,tzinfo=timezone.utc)


def facts():
    plan={'position_id':4,'next_review':(T0+timedelta(hours=8)).isoformat(),
          'expiry':(T0+timedelta(hours=12)).isoformat(),
          'monitoring':{'approved':True,'invalidation_4h_bps':-20,'invalidation_1h_bps':0,'interval_s':900},
          'protective_orders':{'stop_mark':90}}
    bars=[{'m':(T0+timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S'),'c':100-i*.005} for i in range(481)]
    positions=[{'id':4}]
    orders=[{'position_id':4,'order_type':'stop','reduce_only':1,'status':'untriggered','trigger_price':90}]
    return plan,bars,positions,orders


def test_approved_invalidation_is_executed_at_review_even_overnight():
    args=facts();signal=position_watch(*args,now=T0+timedelta(hours=8,minutes=1))
    assert signal['action']=='close' and signal['position_id']==4
    assert signal['return_4h_bps']<=-20 and signal['return_1h_bps']<0


def test_wait_until_review_and_refuse_to_infer_from_stale_data():
    args=facts()
    assert position_watch(*args,now=T0+timedelta(hours=7))['action']=='wait'
    assert position_watch(*args,now=T0+timedelta(hours=9))['reason']=='review awaits fresh completed candles'


def test_restore_missing_stop_expiry_and_closed_positions():
    plan,bars,positions,orders=facts();now=T0+timedelta(hours=8,minutes=1)
    assert position_watch(plan,bars,positions,[],now)['action']=='restore_stop'
    assert position_watch(plan,bars,positions,orders,T0+timedelta(hours=12))['action']=='close'
    assert position_watch(plan,bars,[],orders,now)['action']=='done'


def test_monitor_never_adds_risk_or_invents_rules_for_an_unapproved_plan():
    plan,bars,positions,orders=facts();del plan['monitoring']
    assert position_watch(plan,bars,positions,orders,T0+timedelta(hours=8,minutes=1))['action']=='wait'
    plan,bars,positions,orders=facts()
    for b in bars:b['c']=100.
    signal=position_watch(plan,bars,positions,orders,T0+timedelta(hours=8,minutes=1))
    assert signal['action']=='review' and 'next_review' in signal
