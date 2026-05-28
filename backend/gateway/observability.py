"""
AQuA-QE LKDF — AI Observability Manager
§29: logs de reasoning, tracing de prompts, tempo de inferência,
     custo por execução, score de confiança, explainability.
"""
from __future__ import annotations

import hashlib
import statistics
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Optional


class ObservabilityManager:
    """
    Agrega e analisa logs de execução para fornecer observabilidade completa.
    Thread-safe. Janelas de tempo configuráveis.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # All logs reference (shared with gateway.state.logs)
        self._logs: deque = deque(maxlen=1000)

        # Hourly buckets: { "2024-01-15T14": { provider: {latencies, costs, ...} } }
        self._hourly: dict[str, dict] = {}

        # Running counters
        self._counters: dict[str, Any] = defaultdict(int)
        self._latency_window: deque[float] = deque(maxlen=200)  # last 200 for percentiles
        self._cost_window:    deque[float] = deque(maxlen=200)

    # ── Ingest ────────────────────────────────────────────────

    def record(self, log) -> None:
        """Record a new execution log and update aggregates."""
        with self._lock:
            self._logs.appendleft(log)
            self._update_counters(log)
            self._update_hourly(log)
            self._latency_window.appendleft(log.latency_ms)
            self._cost_window.appendleft(log.cost_usd)

    def _update_counters(self, log) -> None:
        self._counters['total'] += 1
        status = str(log.status.value if hasattr(log.status, 'value') else log.status)
        self._counters[f'status_{status}'] += 1

        provider = str(log.provider.value if hasattr(log.provider, 'value') else log.provider)
        self._counters[f'prov_{provider}'] += 1

        engine = str(log.engine.value if hasattr(log.engine, 'value') else log.engine)
        self._counters[f'eng_{engine}'] += 1

        if log.fallback_used:
            self._counters['fallbacks'] += 1
        if log.error:
            self._counters['errors'] += 1

        self._counters['total_cost_usd_x1m'] += int(log.cost_usd * 1_000_000)
        self._counters['total_input_tokens']  += log.input_tokens
        self._counters['total_output_tokens'] += log.output_tokens

    def _update_hourly(self, log) -> None:
        hour_key = log.timestamp.strftime('%Y-%m-%dT%H') if hasattr(log.timestamp, 'strftime') else str(log.timestamp)[:13]
        if hour_key not in self._hourly:
            self._hourly[hour_key] = defaultdict(list)
        bucket = self._hourly[hour_key]
        provider = str(log.provider.value if hasattr(log.provider, 'value') else log.provider)
        bucket[f'{provider}_latencies'].append(log.latency_ms)
        bucket[f'{provider}_costs'].append(log.cost_usd)
        bucket['all_latencies'].append(log.latency_ms)
        bucket['all_costs'].append(log.cost_usd)
        bucket['requests'].append(1)
        # Keep only last 48 hours
        cutoff = (datetime.utcnow() - timedelta(hours=48)).strftime('%Y-%m-%dT%H')
        self._hourly = {k: v for k, v in self._hourly.items() if k >= cutoff}

    # ── Percentiles ───────────────────────────────────────────

    def percentiles(self, data: list[float]) -> dict:
        if not data:
            return {'p50': 0, 'p75': 0, 'p95': 0, 'p99': 0, 'min': 0, 'max': 0, 'mean': 0}
        s = sorted(data)
        n = len(s)
        def pct(p): return s[min(int(n * p / 100), n - 1)]
        return {
            'p50':  round(pct(50),  1),
            'p75':  round(pct(75),  1),
            'p95':  round(pct(95),  1),
            'p99':  round(pct(99),  1),
            'min':  round(s[0],     1),
            'max':  round(s[-1],    1),
            'mean': round(statistics.mean(s), 1),
        }

    # ── Summary ───────────────────────────────────────────────

    def summary(self) -> dict:
        with self._lock:
            total = self._counters['total'] or 1
            lats  = list(self._latency_window)
            costs = list(self._cost_window)

            success = self._counters['status_success'] + self._counters['status_fallback']
            error   = self._counters['errors']

            return {
                'total_requests':     self._counters['total'],
                'success_rate':       round(success / total * 100, 1),
                'error_rate':         round(error / total * 100, 1),
                'fallback_rate':      round(self._counters['fallbacks'] / total * 100, 1),
                'total_cost_usd':     round(self._counters['total_cost_usd_x1m'] / 1_000_000, 6),
                'total_input_tokens': self._counters['total_input_tokens'],
                'total_output_tokens':self._counters['total_output_tokens'],
                'latency_percentiles':self.percentiles(lats),
                'cost_percentiles':   self.percentiles(costs),
            }

    def by_provider(self) -> dict[str, dict]:
        """Aggregated stats per provider from recent logs."""
        with self._lock:
            result: dict[str, dict] = defaultdict(lambda: {
                'requests': 0, 'errors': 0, 'fallbacks': 0,
                'latencies': [], 'costs': [], 'tokens': 0,
            })
            for log in self._logs:
                p = str(log.provider.value if hasattr(log.provider, 'value') else log.provider)
                r = result[p]
                r['requests'] += 1
                r['latencies'].append(log.latency_ms)
                r['costs'].append(log.cost_usd)
                r['tokens'] += log.input_tokens + log.output_tokens
                if log.error: r['errors'] += 1
                if log.fallback_used: r['fallbacks'] += 1
            out = {}
            for prov, data in result.items():
                pcts = self.percentiles(data['latencies'])
                out[prov] = {
                    'requests':    data['requests'],
                    'errors':      data['errors'],
                    'fallbacks':   data['fallbacks'],
                    'error_rate':  round(data['errors'] / max(data['requests'], 1) * 100, 1),
                    'avg_latency': pcts['mean'],
                    'p95_latency': pcts['p95'],
                    'total_cost':  round(sum(data['costs']), 6),
                    'avg_cost':    round(statistics.mean(data['costs']) if data['costs'] else 0, 8),
                    'total_tokens':data['tokens'],
                }
            return out

    def by_engine(self) -> dict[str, dict]:
        """Aggregated stats per engine."""
        with self._lock:
            result: dict[str, dict] = defaultdict(lambda: {
                'requests': 0, 'latencies': [], 'costs': [], 'errors': 0,
            })
            for log in self._logs:
                e = str(log.engine.value if hasattr(log.engine, 'value') else log.engine)
                r = result[e]
                r['requests'] += 1
                r['latencies'].append(log.latency_ms)
                r['costs'].append(log.cost_usd)
                if log.error: r['errors'] += 1
            out = {}
            for eng, data in result.items():
                pcts = self.percentiles(data['latencies'])
                out[eng] = {
                    'requests':    data['requests'],
                    'avg_latency': pcts['mean'],
                    'p95_latency': pcts['p95'],
                    'total_cost':  round(sum(data['costs']), 6),
                    'error_rate':  round(data['errors'] / max(data['requests'], 1) * 100, 1),
                }
            return out

    def hourly_trend(self, hours: int = 24) -> list[dict]:
        """Returns per-hour aggregates for the last N hours."""
        with self._lock:
            now = datetime.utcnow()
            result = []
            for h in range(hours - 1, -1, -1):
                ts   = now - timedelta(hours=h)
                key  = ts.strftime('%Y-%m-%dT%H')
                bucket = self._hourly.get(key, {})
                lats = bucket.get('all_latencies', [])
                costs = bucket.get('all_costs', [])
                result.append({
                    'hour':          key,
                    'label':         ts.strftime('%H:00'),
                    'requests':      len(bucket.get('requests', [])),
                    'avg_latency':   round(statistics.mean(lats), 1) if lats else 0,
                    'total_cost':    round(sum(costs), 6),
                    'p95_latency':   self.percentiles(lats)['p95'] if lats else 0,
                })
            return result

    def recent_traces(self, limit: int = 20) -> list[dict]:
        """Recent execution traces with full detail."""
        with self._lock:
            traces = []
            for log in list(self._logs)[:limit]:
                provider = str(log.provider.value if hasattr(log.provider, 'value') else log.provider)
                engine   = str(log.engine.value   if hasattr(log.engine,   'value') else log.engine)
                status   = str(log.status.value   if hasattr(log.status,   'value') else log.status)
                traces.append({
                    'id':           log.id[:8],
                    'trace_id':     getattr(log, 'trace_id', log.id[:8]),
                    'timestamp':    log.timestamp.isoformat() if hasattr(log.timestamp, 'isoformat') else str(log.timestamp),
                    'engine':       engine,
                    'provider':     provider,
                    'model':        log.model,
                    'status':       status,
                    'latency_ms':   round(log.latency_ms, 1),
                    'ttft_ms':      round(getattr(log, 'ttft_ms', 0), 1),
                    'input_tokens': log.input_tokens,
                    'output_tokens':log.output_tokens,
                    'cost_usd':     log.cost_usd,
                    'confidence':   round(getattr(log, 'confidence_score', 1.0), 2),
                    'fallback':     log.fallback_used,
                    'fallback_from':getattr(log, 'fallback_from', None),
                    'error':        log.error,
                    'error_type':   getattr(log, 'error_type', None),
                    'prompt_type':  getattr(log, 'prompt_type', ''),
                    'reasoning':    getattr(log, 'reasoning_steps', []),
                    'engine_chain': getattr(log, 'engine_chain', []),
                    'session_id':   getattr(log, 'session_id', None),
                    'deployment':   getattr(log, 'deployment_mode', 'cloud'),
                })
            return traces

    def latency_heatmap(self) -> dict:
        """Provider × Engine latency heatmap data."""
        with self._lock:
            cell: dict[tuple, list] = defaultdict(list)
            for log in self._logs:
                p = str(log.provider.value if hasattr(log.provider, 'value') else log.provider)
                e = str(log.engine.value   if hasattr(log.engine,   'value') else log.engine)
                cell[(p, e)].append(log.latency_ms)
            providers = sorted(set(k[0] for k in cell))
            engines   = sorted(set(k[1] for k in cell))
            matrix = []
            for p in providers:
                row = []
                for e in engines:
                    lats = cell.get((p, e), [])
                    row.append(round(statistics.mean(lats), 1) if lats else None)
                matrix.append(row)
            return {'providers': providers, 'engines': engines, 'matrix': matrix}

    def cost_breakdown(self) -> dict:
        """Cost breakdown by provider and model."""
        with self._lock:
            by_model: dict[str, float] = defaultdict(float)
            by_hour:  dict[str, float] = defaultdict(float)
            for log in self._logs:
                model = log.model or 'unknown'
                by_model[model] += log.cost_usd
                hour = log.timestamp.strftime('%Y-%m-%dT%H') if hasattr(log.timestamp, 'strftime') else str(log.timestamp)[:13]
                by_hour[hour] += log.cost_usd
            return {
                'by_model': {k: round(v, 6) for k, v in sorted(by_model.items(), key=lambda x: -x[1])},
                'by_hour':  {k: round(v, 6) for k, v in sorted(by_hour.items())},
            }

    def confidence_distribution(self) -> dict:
        """Distribution of confidence scores."""
        with self._lock:
            buckets = {'0-50': 0, '50-70': 0, '70-85': 0, '85-95': 0, '95-100': 0}
            for log in self._logs:
                c = getattr(log, 'confidence_score', 1.0) * 100
                if c < 50:    buckets['0-50']   += 1
                elif c < 70:  buckets['50-70']  += 1
                elif c < 85:  buckets['70-85']  += 1
                elif c < 95:  buckets['85-95']  += 1
                else:         buckets['95-100'] += 1
            return buckets

    def set_log_source(self, logs_deque: deque) -> None:
        """Attach to gateway's existing log deque (shared reference)."""
        with self._lock:
            self._logs = logs_deque


# Singleton
observability = ObservabilityManager()


# ── Helpers ──────────────────────────────────────────────────

def compute_confidence(status: str, fallback: bool, error: str | None, latency_ms: float) -> float:
    """Heuristic confidence score 0–1."""
    score = 1.0
    if error:        score -= 0.5
    if fallback:     score -= 0.2
    if 'failed' in status.lower(): score -= 0.4
    if latency_ms > 10000: score -= 0.1
    if latency_ms > 30000: score -= 0.2
    return max(0.0, min(1.0, round(score, 2)))


def classify_error(error_msg: str | None) -> str | None:
    """Classify error type from message."""
    if not error_msg: return None
    msg = error_msg.lower()
    if 'timeout' in msg or 'timed out' in msg: return 'timeout'
    if '401' in msg or 'auth' in msg or 'key' in msg: return 'auth'
    if '429' in msg or 'rate' in msg or 'quota' in msg: return 'rate_limit'
    if '503' in msg or 'demand' in msg or 'overload' in msg: return 'overload'
    if '400' in msg or 'invalid' in msg or 'format' in msg: return 'model_error'
    if 'connect' in msg or 'network' in msg or 'fetch' in msg: return 'network'
    return 'unknown'


def prompt_hash(system_prompt: str | None) -> str:
    if not system_prompt: return ''
    return hashlib.sha256(system_prompt.encode()).hexdigest()[:8]
