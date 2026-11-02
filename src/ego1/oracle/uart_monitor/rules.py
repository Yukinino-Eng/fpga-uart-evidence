"""Deterministic event rules using capture ticks, independent of UI scheduling."""
import operator

HZ=100000000
OPERATORS=dict(lt=operator.lt,le=operator.le,gt=operator.gt,ge=operator.ge,eq=operator.eq,ne=operator.ne)


class RuleEngine:
    def __init__(self, profile, start_ticks=0):
        self.profile=profile
        self.last_frame_ticks=start_ticks
        self.states={}
        self.events_total=0
        self.timeout_ticks=int(profile['timing']['valid_frame_timeout_ms']*HZ/1000)
        self.local_fault=False
        self.history_counts={}
        self.behavior=None
        if profile.get('analysis'):
            from .behavior import BehaviorEngine
            self.behavior=BehaviorEngine(profile)

    def _condition(self, rule, frame):
        field=rule['field']
        if rule['kind']=='invalid':
            return not frame['validity'].get(field,False)
        if not frame['validity'].get(field,False):
            return None
        value=frame['fields'][field]
        if rule['kind']=='range':return not rule['min']<=value<=rule['max']
        if rule['kind']=='compare':return OPERATORS[rule['op']](value,rule['value'])
        if rule['kind']=='bits':return int(frame['raw_fields'][field]) & rule['mask']==rule['equals']
        raise ValueError('Unsupported rule')

    def _event(self, identity, category, ticks, evidence):
        self.events_total+=1
        self.history_counts[identity]=self.history_counts.get(identity,0)+1
        return dict(event_id=self.events_total,rule_id=identity,category=category,
                    trigger_ticks=ticks,evidence=evidence)

    def _transition(self, identity, condition, ticks, duration, evidence, category):
        if not condition:
            self.states.pop(identity,None)
            return None
        state=self.states.setdefault(identity,dict(since=ticks,triggered=False))
        if not state['triggered'] and ticks-state['since']>=duration:
            state['triggered']=True
            return self._event(identity,category,ticks,evidence)
        return None

    def update(self, frames, issues, now_ticks, drained=True, local_ok=True):
        events=[]
        self.local_fault=not local_ok or not drained
        if self.behavior and not local_ok:
            self.behavior.reset('local_capture_unreliable')
        ordered=[(f['end_ticks'],1,f) for f in frames]+[(i['ticks'],0,i) for i in issues]
        for tick,kind,item in sorted(ordered,key=lambda x:(x[0],x[1])):
            if kind==0:
                # Broken continuity never contributes to a field persistence interval.
                self.states={k:v for k,v in self.states.items() if k.startswith('local:') or k=='valid_frame_timeout'}
                events.append(self._event('protocol:'+item['kind'],'protocol',tick,item))
                if self.behavior:self.behavior.reset('protocol:'+item['kind'])
                continue
            if tick-self.last_frame_ticks>=self.timeout_ticks:
                if local_ok:
                    due=self.last_frame_ticks+self.timeout_ticks
                    missed=self._transition('valid_frame_timeout',True,due,0,
                                            dict(last_valid_ticks=self.last_frame_ticks,deadline_ticks=due),'protocol')
                    if missed:events.append(missed)
                self.states.clear()
                if self.behavior:self.behavior.reset('valid_frame_gap')
            if self.behavior and tick<self.last_frame_ticks:
                self.behavior.reset('capture_time_restart')
            self.last_frame_ticks=tick
            self.states.pop('valid_frame_timeout',None)
            for rule in self.profile['rules']:
                condition=self._condition(rule,item)
                event=self._transition(rule['id'],condition,tick,int(rule['duration_ms']*HZ/1000),
                                       dict(field=rule['field'],value=item['fields'][rule['field']],
                                            raw_value=item['raw_fields'][rule['field']],
                                            raw_start=item['raw_start'],raw_end=item['raw_end']), 'device')
                if event:events.append(event)
            if self.behavior and local_ok:
                behavior_events,_=self.behavior.feed(item)
                for event in behavior_events:
                    events.append(self._event(event['rule_id'],event['category'],event['trigger_ticks'],event['evidence']))
        # Do not call a local receiver backlog a target-device silence.
        if not self.local_fault:
            due=self.last_frame_ticks+self.timeout_ticks
            event=self._transition('valid_frame_timeout',now_ticks>=due,due,0,
                                   dict(last_valid_ticks=self.last_frame_ticks,deadline_ticks=due),'protocol')
            if event:events.append(event)
        # Suppress new timeouts during local backlog/failure, but retain an
        # already emitted timeout until a valid frame recovers it. Clearing the
        # latch on a transient not-drained poll repeats the same deadline.
        return events

    def recovered(self):
        return not self.local_fault and not self.states and (not self.behavior or not self.behavior.states)

    def behavior_status(self):
        return self.behavior.summary() if self.behavior else None
