"""Pure result/time selector. Dates are priorities, not admission gates.

N is no completed answer ever; R is old, including early/same-day practice.
Parameters describe a product policy, not optimal learning intervals.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import math

POLICY = 'short-round-result-spacing-v7'
BATCH_SIZE = 10
DAY = 86400


def number(value, default=0):
    return value if type(value) in (int,float) and math.isfinite(value) else default


def _items(candidates):
    result, seen = [], set()
    for raw in sorted((row for row in candidates if isinstance(row,dict)),key=lambda row:str(row.get('id',''))):
        if (not isinstance(raw.get('id'),str) or not raw['id'] or raw['id'] in seen
                or raw.get('pool') not in ('N','R','F') or raw.get('source_key') is None):
            continue
        item=deepcopy(raw)
        item['pool']='N' if item['pool']=='N' else 'R'
        seen.add(item['id']); result.append(item)
    return result


def plan(candidates, now=None, limit=BATCH_SIZE):
    now=number(now); limit=max(0,min(BATCH_SIZE,int(limit)))
    items=_items(candidates); counts=Counter(row['pool'] for row in items)
    new=min(counts['N'],int(limit*.6+.5))
    phase='new_first' if new else 'review_only'
    return dict(policy=POLICY,phase=phase,stage=phase,target_mix={'N':new,'R':limit-new},
        available={'N':counts['N'],'R':counts['R'],'F':0},
        overdue_three_days=sum(row['pool']=='R' and now-number(row.get('next_due'),now)>=3*DAY for row in items))


def priority(item, now):
    latest=number(item.get('last_submitted'))
    anchor=latest or number(item.get('learned'),number(item.get('created'),now))
    elapsed=max(0,now-anchor); planned=max(DAY,number(item.get('interval_days'),1)*DAY)
    time_need=elapsed/planned
    recent=item.get('practice_learning') or {}
    outcomes=recent.get('outcomes',[]) if isinstance(recent,dict) else []
    outcomes=[value for value in outcomes if value in ('pass','improve','blunder')][:5]
    failure=sum(value!='pass' for value in outcomes)/len(outcomes) if outcomes else 0
    latest_failure=bool(outcomes and outcomes[0]!='pass')
    wait=max(0,now-number(item.get('ticket'),anchor))/DAY
    weight=1+min(3,time_need)+failure+.5*latest_failure+min(1,wait/30)
    return weight,dict(time_need=round(time_need,6),recent_failure_rate=round(failure,6),
        latest_failure=latest_failure,waiting_days=round(wait,6))


def select(candidates, *, limit=BATCH_SIZE, first='N', seed=None, now=None,
           recent_sources=(), recent_tasks=(), protected_sources=()):
    """Fill quotas and borrow either way; every supplied reliable item can enter.

    Compatibility arguments do not restore exposure gates or cause multipliers.
    """
    from app.training_schedule_v6 import _separate_games
    now,seed=number(now),str(seed or 'result-spacing-default-v7')
    limit=max(0,min(BATCH_SIZE,int(limit))); items=_items(candidates)
    details=plan(items,now,limit)
    target,selected,covered,used=details['target_mix'],[],set(),Counter()
    recent=set(recent_sources); totals=Counter(); draws=0

    def add(item,mode,count):
        weight,components=priority(item,now)
        item['ordering_reason']=[
            '按等待顺序保留轮转机会' if mode=='coverage_oldest' else '根据实际间隔和近期有效结果安排',
            '尚未完成答题的新题' if item['pool']=='N' else '已完成过答题的旧题，推荐时间影响顺序']
        item['selection_meta']=dict(policy=POLICY,seed=seed,seed_strategy='sha256-counter-v1',
            now=now,mode=mode,pool=item['pool'],target_mix=dict(target),available=details['available'],
            weight=weight,weight_components=components,ticket=item.get('ticket'),eligible_items=count,
            source_aggregation='max',source_recent=item['source_key'] in recent)
        selected.append(item);items.remove(item);totals[item['pool']]+=1;used[item['source_key']]+=1

    def oldest(rows):
        return min(rows,key=lambda row:(number(row.get('ticket'),now),row['id']))

    def draw(rows):
        nonlocal draws
        distinct=[row for row in rows if not used[row['source_key']]]
        rows=distinct or rows
        groups={}
        for row in rows:groups.setdefault(row['source_key'],[]).append(row)
        draws+=1
        def pick(values,suffix):
            raw=hashlib.sha256(f'{seed}:{draws}:{suffix}'.encode()).digest()
            at=(int.from_bytes(raw[:8],'big')+.5)/2**64*sum(weight for _,weight in values)
            for value,weight in values:
                at-=weight
                if at<0:return value
            return values[-1][0]
        source=pick([(key,max(priority(row,now)[0] for row in groups[key]))
            for key in sorted(groups,key=str)],'source')
        return pick([(row,priority(row,now)[0]) for row in groups[source]],'item')

    while items and len(selected)<limit:
        deficits={pool:max(0,target[pool]-totals[pool]) for pool in ('N','R')}
        usable=[pool for pool in ('N','R') if deficits[pool] and any(row['pool']==pool for row in items)]
        if usable:
            pool=max(usable,key=lambda value:(deficits[value],value==first))
            rows=[row for row in items if row['pool']==pool]
        else:rows=list(items)
        uncovered=[row for row in rows if row['pool'] not in covered]
        if uncovered:
            item=oldest(uncovered);mode='coverage_oldest';covered.add(item['pool'])
        else:item=draw(rows);mode='time_result_draw'
        add(item,mode,len(rows))
    actual={'N':totals['N'],'R':totals['R'],'F':0}
    for row in selected:
        row['selection_meta'].update(actual_mix=actual,selected_count=len(selected),selected_sources=len(used),
            nominal_target_unfilled={key:max(0,target[key]-totals[key]) for key in target})
    return _separate_games(selected)
