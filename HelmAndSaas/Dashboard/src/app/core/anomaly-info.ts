import { AnomalyType } from './models';

export interface AnomalyInfo {
  /** what a person calls it */
  label: string;
  /** one sentence: what the detector saw */
  what: string;
  /** what to do about it */
  hint: string;
}

/** Plain-language names for the model's four verdicts. The raw code stays visible in tooltips and tables. */
export const ANOMALY_INFO: Record<AnomalyType, AnomalyInfo> = {
  NORMAL: { label: 'Healthy', what: 'No problem detected.', hint: '' },
  CPU_HOG: {
    label: 'CPU overload',
    what: 'The service is using far more CPU than usual.',
    hint: 'Look for a runaway loop or a traffic spike. Raise the CPU limit or add replicas.',
  },
  MEMORY_LEAK: {
    label: 'Memory pressure',
    what: 'Memory use is abnormal and may keep growing (a leak).',
    hint: 'Restarting the pod recovers it; look for a leak in a recent release.',
  },
  NETWORK_DELAY: {
    label: 'Slow responses',
    what: 'The service answers much more slowly than usual (network or overload).',
    hint: 'Check the network path and the services it calls; add replicas if it is overloaded.',
  },
};

export const ANOMALY_TYPES: AnomalyType[] = ['CPU_HOG', 'MEMORY_LEAK', 'NETWORK_DELAY'];

/**
 * The model's confidence is not a calibrated probability (it is close to 100 % for almost every verdict), so it is shown as a
 * word; the exact figure stays in the tooltip.
 */
export function confidenceWord(c: number): string {
  return c >= 0.9 ? 'High' : c >= 0.7 ? 'Medium' : 'Low';
}

/** "12 s ago", "3 min ago", "2 h ago", "5 d ago" from a number of seconds */
export function agoSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return 'never';
  const v = Math.max(0, Math.round(s));
  if (v < 5) return 'just now';
  if (v < 60) return `${v} s ago`;
  if (v < 3600) return `${Math.floor(v / 60)} min ago`;
  if (v < 86400) return `${Math.floor(v / 3600)} h ago`;
  return `${Math.floor(v / 86400)} d ago`;
}

export function agoDate(iso: string | null | undefined, nowMs = Date.now()): string {
  if (!iso) return 'never';
  const t = Date.parse(iso);
  return Number.isFinite(t) ? agoSeconds((nowMs - t) / 1000) : 'never';
}

/** "45 s", "2 min 10 s", "1 h 5 min" */
export function durationText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ''}`;
  return `${Math.floor(s / 3600)} h${Math.floor((s % 3600) / 60) ? ` ${Math.floor((s % 3600) / 60)} min` : ''}`;
}

/** What a remediation action does, in a sentence (params are the rule stored with the action). */
export function actionText(action: string, params: Record<string, unknown> | null | undefined): string {
  switch (action) {
    case 'THROTTLE_CPU':
      return `Capped the CPU limit at ${params?.['cpu_limit'] ?? 'the configured value'}`;
    case 'RESTART_POD':
      return 'Restarted the service\'s pod(s)';
    case 'SCALE_UP':
      return `Added ${params?.['replica_increase'] ?? 1} replica(s)`;
    default:
      return action;
  }
}
