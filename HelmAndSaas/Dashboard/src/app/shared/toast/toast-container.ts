import { Component } from '@angular/core';
import { ToastKind, ToastService } from '../../core/toast.service';

const STYLES: Record<ToastKind, string> = {
  anomaly: 'border-l-rose-500 bg-white dark:bg-slate-800',
  'remediation-success': 'border-l-emerald-500 bg-white dark:bg-slate-800',
  'remediation-failed': 'border-l-orange-500 bg-white dark:bg-slate-800',
};

const ICONS: Record<ToastKind, string> = {
  anomaly: '⚠',
  'remediation-success': '✓',
  'remediation-failed': '✕',
};

@Component({
  selector: 'app-toast-container',
  template: `
    <div class="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      @for (t of toast.toasts(); track t.id) {
        <div
          class="pointer-events-auto flex items-start gap-2 rounded-lg border-l-4 border border-slate-200 p-3 shadow-lg dark:border-slate-700"
          [class]="styles[t.kind]"
        >
          <span class="mt-0.5 text-sm">{{ icons[t.kind] }}</span>
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-slate-900 dark:text-slate-100">{{ t.title }}</p>
            <p class="truncate text-xs text-slate-500 dark:text-slate-400">{{ t.detail }}</p>
          </div>
          <button
            (click)="toast.dismiss(t.id)"
            class="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      }
    </div>
  `,
})
export class ToastContainer {
  readonly styles = STYLES;
  readonly icons = ICONS;

  constructor(protected readonly toast: ToastService) {}
}
