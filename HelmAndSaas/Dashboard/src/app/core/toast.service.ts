import { Injectable, signal } from '@angular/core';

export type ToastKind = 'anomaly' | 'remediation-success' | 'remediation-failed';

export interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  detail: string;
}

const AUTO_DISMISS_MS = 6000;

@Injectable({ providedIn: 'root' })
export class ToastService {
  private nextId = 0;
  readonly toasts = signal<ToastItem[]>([]);

  show(kind: ToastKind, title: string, detail: string): void {
    const id = ++this.nextId;
    this.toasts.update((list) => [...list, { id, kind, title, detail }]);
    setTimeout(() => this.dismiss(id), AUTO_DISMISS_MS);
  }

  dismiss(id: number): void {
    this.toasts.update((list) => list.filter((t) => t.id !== id));
  }
}
