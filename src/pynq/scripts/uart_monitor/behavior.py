"""Mode-aware, explainable behavior checks over decoded frames (Python 3.6)."""
from collections import deque
import copy
import hashlib
import json
import math
import re
from statistics import median

HZ = 100000000
STATS = ('median', 'mad', 'iqr', 'p90_abs')


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def protocol_fingerprint(profile):
    return fingerprint({k: profile.get(k) for k in ('framing', 'fields', 'checksum', 'sequence')})


def analysis_fingerprint(config):
    return fingerprint({k: v for k, v in config.items() if k != 'model'})


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid behavior parameter: ' + name)


def _identifier(value):
    if not isinstance(value, str) or not re.match(r'^[a-z][a-z0-9_]{0,63}$', value):
        raise ValueError('Behavior identifiers must be lowercase ASCII names')


def validate_analysis(profile):
    """Normalize and validate the optional analysis config before any hardware access."""
    config = profile.get('analysis')
    if config is None:
        return None
    if not isinstance(config, dict) or config.get('version') != 1:
        raise ValueError('Expected analysis.version=1')
    fields = {f['name']: f for f in profile['fields']}
    modes = config.get('modes', [])
    if not isinstance(modes, list) or not 1 <= len(modes) <= 16:
        raise ValueError('Behavior needs 1..16 operating modes')
    mode_ids = set()
    for mode in modes:
        _identifier(mode['id'])
        if mode['id'] in mode_ids:
            raise ValueError('Duplicate operating mode')
        mode_ids.add(mode['id'])
        gate = mode.get('when')
        if gate is None:
            if len(modes) != 1:
                raise ValueError('Unconditional mode must be the only mode')
        else:
            field = fields.get(gate.get('field'))
            if field is None or field['type'] == 'float32':
                raise ValueError('Mode gate requires an integer field')
            if any(type(gate.get(k)) is not int for k in ('mask', 'equals')):
                raise ValueError('Mode gate requires integer mask/equals')
            if gate['mask'] < 0 or gate['equals'] < 0 or gate['equals'] & ~gate['mask']:
                raise ValueError('Invalid mode mask/equals')
    def references(rule):
        if rule.get('field') not in fields:
            raise ValueError('Unknown behavior field')
        selected = rule.setdefault('modes', [m['id'] for m in modes])
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= mode_ids:
            raise ValueError('Unknown or duplicate behavior mode')
    ids = set()
    freshness = config.setdefault('freshness', [])
    if len(freshness) > 32:
        raise ValueError('Too many freshness checks')
    for rule in freshness:
        _identifier(rule['id'])
        if rule['id'] in ids:
            raise ValueError('Duplicate behavior check')
        ids.add(rule['id']); references(rule)
        dtype = fields[rule['field']]['type']
        if not dtype.startswith('u'):
            raise ValueError('Freshness requires an unsigned cumulative counter')
        bits = rule.setdefault('bits', int(dtype[1:]))
        if type(bits) is not int or not 1 <= bits <= int(dtype[1:]):
            raise ValueError('Invalid freshness counter width')
        _number(rule.get('max_stale_ms'), 'max_stale_ms', 1, 60000)
        valid = rule.setdefault('valid_fields', [rule['field']])
        if not isinstance(valid, list) or not valid or any(k not in fields for k in valid):
            raise ValueError('Invalid freshness validity fields')
    baseline = config.get('baseline')
    if baseline is not None:
        _number(baseline.get('window_ms'), 'window_ms', 20, 60000)
        _number(baseline.get('step_ms'), 'step_ms', 1, baseline['window_ms'])
        for key, default, lo, hi in (('min_samples', 10, 2, 4096), ('max_samples', 4096, 2, 100000),
                                     ('min_training_windows', 20, 2, 20000)):
            value = baseline.setdefault(key, default)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError('Invalid baseline ' + key)
        if baseline['min_samples'] > baseline['max_samples']:
            raise ValueError('Baseline sample limits reversed')
        _number(baseline.setdefault('min_training_seconds', 5), 'min_training_seconds', 1, 3600)
        _number(baseline.setdefault('mad_multiplier', 6), 'mad_multiplier', 1, 100)
        features = baseline.get('features', [])
        if not 1 <= len(features) <= 32:
            raise ValueError('Baseline needs 1..32 features')
        for feature in features:
            _identifier(feature['id'])
            if feature['id'] in ids:
                raise ValueError('Duplicate behavior check')
            ids.add(feature['id']); references(feature)
            if feature.get('stat') not in STATS:
                raise ValueError('Unsupported robust window feature')
            _number(feature.get('margin_floor'), 'margin_floor', 1e-12, 1e30)
            _number(feature.setdefault('duration_ms', 400), 'duration_ms', 0, 60000)
            if feature.setdefault('direction', 'both') not in ('both', 'upper', 'lower'):
                raise ValueError('Invalid baseline bound direction')
    if not freshness and baseline is None:
        raise ValueError('Empty behavior analysis')
    model = config.get('model')
    if model is not None:
        if baseline is None or model.get('version') != 1:
            raise ValueError('Model requires baseline config and version=1')
        if model.get('protocol_sha256') != protocol_fingerprint(profile):
            raise ValueError('Baseline model protocol/units mismatch')
        if model.get('analysis_sha256') != analysis_fingerprint(config):
            raise ValueError('Baseline model analysis config mismatch')
        if model.get('model_id') != fingerprint({k: v for k, v in model.items() if k != 'model_id'}):
            raise ValueError('Baseline model digest mismatch')
        expected = {(m, f['id']): f for f in baseline['features'] for m in f['modes']}
        for mode, entries in model.get('modes', {}).items():
            for name, entry in entries.items():
                feature = expected.get((mode, name))
                if feature is None:
                    raise ValueError('Model has an unknown mode/feature')
                for key in ('center', 'mad', 'margin'):
                    _number(entry.get(key), key, -1e30 if key == 'center' else 0, 1e30)
                margin = max(feature['margin_floor'], baseline['mad_multiplier'] * entry['mad'])
                if entry['margin'] != margin:
                    raise ValueError('Model margin does not match the frozen config')
                if type(entry.get('windows')) is not int or entry['windows'] < baseline['min_training_windows']:
                    raise ValueError('Insufficient model training windows')
        if not model.get('modes'):
            raise ValueError('Empty baseline model')
    json.dumps(config, allow_nan=False)
    return config


def feature_value(values, statistic):
    center = median(values)
    if statistic == 'median':
        return center
    if statistic == 'mad':
        return median([abs(v - center) for v in values])
    if statistic == 'iqr':
        ordered = sorted(values)
        return ordered[int(math.ceil(.75 * len(ordered))) - 1] - ordered[int(math.ceil(.25 * len(ordered))) - 1]
    if statistic == 'p90_abs':
        ordered = sorted(abs(v) for v in values)
        return ordered[int(math.ceil(.9 * len(ordered))) - 1]
    raise ValueError('Unknown feature')


class BehaviorEngine:
    """Read-only analysis: no hardware, protocol mutation, or online model updates."""
    def __init__(self, profile):
        self.config = validate_analysis(profile)
        self.states = {}; self.progress = {}; self.window = deque()
        self.mode = None; self.last_tick = None; self.window_origin = None; self.last_window = None
        self.window_ready = False; self.freshness_status = {}
        self.evaluated = set(); self.observed = set(); self.resets = {}; self.last_reason = 'not_started'
        self.windows = 0; self.generation = 0; self.deviations_total = 0

    def reset(self, reason):
        self.states.clear(); self.progress.clear(); self.window.clear()
        self.last_tick = None; self.window_origin = None; self.last_window = None
        self.window_ready = False
        self.freshness_status = {r['id']: 'UNKNOWN' for r in self.config['freshness']}
        self.last_reason = reason
        self.generation += 1
        self.resets[reason] = self.resets.get(reason, 0) + 1

    def _mode(self, frame):
        matches = []
        for mode in self.config['modes']:
            gate = mode.get('when')
            if gate is None or (frame['validity'].get(gate['field'], False) and
                                int(frame['raw_fields'][gate['field']]) & gate['mask'] == gate['equals']):
                matches.append(mode['id'])
        return matches[0] if len(matches) == 1 else None

    def _check(self, identity, condition, tick, duration, evidence):
        if not condition:
            self.states.pop(identity, None)
            return None
        state = self.states.setdefault(identity, dict(since=tick, triggered=False))
        if state['triggered'] or tick - state['since'] < duration:
            return None
        state['triggered'] = True
        baseline = identity.startswith('behavior:baseline:')
        return dict(rule_id=identity, category='behavior' if baseline else 'device', trigger_ticks=tick,
                    evidence=dict(evidence, first_suspect_ticks=state['since'], confirmation_ticks=tick,
                                  finding_type='baseline_deviation' if baseline else 'counter_not_advancing',
                                  interpretation='Observed behavior anomaly; root cause is not identified'))

    def feed(self, frame):
        events = []; observations = []
        tick = frame['end_ticks']; mode = self._mode(frame)
        if tick < 0 or (self.last_tick is not None and tick <= self.last_tick):
            self.reset('time_not_increasing')
        if mode != self.mode:
            self.reset('mode_change'); self.mode = mode
        self.last_tick = tick
        if mode is None:
            self.reset('unknown_or_ambiguous_mode')
            return events, observations
        for rule in self.config['freshness']:
            name = 'behavior:freshness:' + rule['id']
            valid = all(frame['validity'].get(k, False) for k in rule['valid_fields'] + [rule['field']])
            if mode not in rule['modes'] or not valid:
                self.progress.pop(name, None); self.states.pop(name, None)
                self.freshness_status[rule['id']] = 'UNKNOWN' if mode in rule['modes'] else 'NOT_APPLICABLE'
                continue
            value = int(frame['raw_fields'][rule['field']]); modulus = 1 << rule['bits']
            previous = self.progress.get(name)
            if previous is None:
                previous = dict(value=value, tick=tick, raw_start=frame['raw_start'])
            elif value != previous['value']:
                delta = (value - previous['value']) % modulus
                if delta >= modulus // 2:
                    self.reset('counter_restart_or_out_of_order')
                previous = dict(value=value, tick=tick, raw_start=frame['raw_start'])
                self.states.pop(name, None)
            self.progress[name] = previous
            age = tick - previous['tick']
            self.freshness_status[rule['id']] = 'STALE' if age >= rule['max_stale_ms'] * HZ / 1000 else 'MONITORING'
            event = self._check(name, age >= rule['max_stale_ms'] * HZ / 1000, tick, 0,
                                dict(field=rule['field'], mode=mode, value=value, stale_ms=age * 1000 / HZ,
                                     max_stale_ms=rule['max_stale_ms'], last_change_ticks=previous['tick'],
                                     raw_start=previous['raw_start'], raw_end=frame['raw_end']))
            if event:
                events.append(event)
        baseline = self.config.get('baseline')
        if baseline is None:
            return events, observations
        features = [f for f in baseline['features'] if mode in f['modes']]
        if not features:
            return events, observations
        if not all(frame['validity'].get(f['field'], False) and
                   isinstance(frame['fields'].get(f['field']), (int, float)) and
                   math.isfinite(frame['fields'][f['field']]) for f in features):
            # Invalid values interrupt persistence; they never become numeric zero.
            self.window.clear(); self.window_origin = None; self.last_window = None
            self.window_ready = False
            self.states = {k: v for k, v in self.states.items() if not k.startswith('behavior:baseline:')}
            self.last_reason = 'invalid_baseline_field'
            self.generation += 1
            return events, observations
        if self.window_origin is None:
            self.window_origin = tick
        self.window.append(frame)
        begin = tick - int(baseline['window_ms'] * HZ / 1000)
        while self.window and self.window[0]['end_ticks'] < begin:
            self.window.popleft()
        if len(self.window) > baseline['max_samples']:
            raise RuntimeError('Behavior window capacity exceeded; analysis cannot continue reliably')
        if tick - self.window_origin < baseline['window_ms'] * HZ / 1000 or len(self.window) < baseline['min_samples']:
            self.window_ready = False
            self.states = {k: v for k, v in self.states.items() if not k.startswith('behavior:baseline:')}
            return events, observations
        if self.last_window is not None and tick - self.last_window < baseline['step_ms'] * HZ / 1000:
            return events, observations
        self.last_window = tick; self.windows += 1; self.window_ready = True
        for feature in features:
            values = [f['fields'][feature['field']] for f in self.window]
            value = feature_value(values, feature['stat'])
            observation = dict(mode=mode, feature_id=feature['id'], value=value, ticks=tick,
                               continuity_id=self.generation,
                               window_start_ticks=self.window[0]['end_ticks'], samples=len(values),
                               raw_start=self.window[0]['raw_start'], raw_end=frame['raw_end'])
            observations.append(observation); self.observed.add((mode, feature['id']))
            bounds = self.config.get('model', {}).get('modes', {}).get(mode, {}).get(feature['id'])
            if bounds is None:
                continue
            self.evaluated.add((mode, feature['id']))
            lower, upper = bounds['center'] - bounds['margin'], bounds['center'] + bounds['margin']
            condition = ((feature['direction'] != 'upper' and value < lower) or
                         (feature['direction'] != 'lower' and value > upper))
            event = self._check('behavior:baseline:' + mode + ':' + feature['id'], condition, tick,
                                int(feature['duration_ms'] * HZ / 1000),
                                dict(observation, field=feature['field'], statistic=feature['stat'],
                                     lower=lower, upper=upper, center=bounds['center'],
                                     model_id=self.config['model']['model_id']))
            if event:
                self.deviations_total += 1
                events.append(event)
        return events, observations

    def summary(self):
        baseline = self.config.get('baseline')
        needed = {(m, f['id']) for f in baseline['features'] for m in f['modes']} if baseline else set()
        unassessed = sorted(m + ':' + f for m, f in needed - self.evaluated)
        applicable = [f for f in baseline['features'] if self.mode in f['modes']] if baseline else []
        modeled = self.config.get('model', {}).get('modes', {}).get(self.mode, {})
        current = 'NOT_APPLICABLE' if not applicable else ('UNTRAINED' if any(f['id'] not in modeled for f in applicable)
                   else ('MONITORING' if self.window_ready else 'WARMUP'))
        return dict(mode=self.mode, windows=self.windows, active_conditions=sorted(self.states),
                    current_baseline_state=current, freshness=self.freshness_status,
                    model_id=self.config.get('model', {}).get('model_id'), unassessed=unassessed,
                    deviations_total=self.deviations_total,
                    baseline_assessment='UNKNOWN' if unassessed else ('DEVIATION_OBSERVED' if self.deviations_total else 'OBSERVED'),
                    resets=self.resets, last_reset=self.last_reason)


def fit_baseline(profile, frames, provenance):
    """Fit only explicitly supplied nominal data. Never called by live capture."""
    result = copy.deepcopy(profile)
    config = validate_analysis(result)
    if config is None or not config.get('baseline'):
        raise ValueError('No baseline feature configuration')
    config.pop('model', None)
    engine = BehaviorEngine(result); samples = {}; coverage = {}; total = 0
    first = last = None
    timeout = int(result['timing']['valid_frame_timeout_ms'] * HZ / 1000)
    previous = None
    for frame in frames:
        tick = frame['end_ticks']
        if previous is not None and (tick <= previous or tick - previous >= timeout):
            engine.reset('training_discontinuity')
        previous = tick; total += 1
        if first is None:
            first = tick
        last = tick
        events, observations = engine.feed(frame)
        if events:
            raise ValueError('Declared nominal data contains a freshness anomaly')
        for observation in observations:
            key = (observation['mode'], observation['feature_id'])
            values = samples.setdefault(key, [])
            if len(values) >= 20000:
                raise ValueError('Training limit is 20000 windows per feature')
            values.append(observation['value'])
            # Sum observed window steps; separated intervals do not fill missing data.
            state = coverage.setdefault(key, dict(last=None, generation=None, ticks=0))
            if state['last'] is not None and state['generation']==observation['continuity_id']:
                state['ticks'] += observation['ticks'] - state['last']
            state['last'] = observation['ticks']
            state['generation'] = observation['continuity_id']
    baseline = config['baseline']; modes = {}
    by_id = {f['id']: f for f in baseline['features']}
    for key, values in samples.items():
        if len(values) < baseline['min_training_windows'] or coverage[key]['ticks'] < baseline['min_training_seconds'] * HZ:
            continue
        center = median(values); spread = median([abs(v - center) for v in values])
        margin = max(by_id[key[1]]['margin_floor'], baseline['mad_multiplier'] * spread)
        modes.setdefault(key[0], {})[key[1]] = dict(center=center, mad=spread, margin=margin,
                                                 windows=len(values), observed_seconds=coverage[key]['ticks'] / HZ)
    if not modes:
        raise ValueError('Insufficient nominal windows/duration; no model was produced')
    model = dict(version=1, protocol_sha256=protocol_fingerprint(result),
                 analysis_sha256=analysis_fingerprint(config), modes=modes,
                 training=dict(provenance, frames=total, first_ticks=first, last_ticks=last,
                               note='Overlapping windows are correlated, not independent trials; validate on separate data'))
    model['model_id'] = fingerprint(model); config['model'] = model
    validate_analysis(result)
    return result
