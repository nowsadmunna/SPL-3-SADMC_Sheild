import { Injectable, signal } from '@angular/core';
import { WS_BASE_URL } from './api-config';
import { EventFrame } from './models';
import { AuthService } from './auth.service';

const RECONNECT_DELAY_MS = 3000;

@Injectable({ providedIn: 'root' })
export class EventsService {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  /** Emits every frame received; consumers filter by cluster_uuid/type themselves. */
  readonly lastFrame = signal<EventFrame | null>(null);

  constructor(private readonly auth: AuthService) {}

  connect(): void {
    const token = this.auth.accessToken();
    if (!token || this.socket) return;

    this.intentionallyClosed = false;
    this.socket = new WebSocket(`${WS_BASE_URL}/ws/events`, ['Bearer', token]);

    this.socket.onmessage = (event) => {
      try {
        this.lastFrame.set(JSON.parse(event.data) as EventFrame);
      } catch {
        // ignore malformed frames
      }
    };

    this.socket.onclose = () => {
      this.socket = null;
      if (!this.intentionallyClosed) {
        this.reconnectTimer = setTimeout(() => this.connect(), RECONNECT_DELAY_MS);
      }
    };

    this.socket.onerror = () => {
      this.socket?.close();
    };
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
  }
}
