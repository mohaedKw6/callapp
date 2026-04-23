import { NativeModule, requireNativeModule, EventSubscription } from 'expo-modules-core';

export type CallProtocol = 'tls' | 'tcp' | 'udp';

export interface StartCallOptions {
  username: string;
  password: string;
  domain: string;
  port: number;
  protocol: CallProtocol;
  destination: string;
  callLimitSec?: number;
}

export type CallStateName =
  | 'idle'
  | 'outgoing_init'
  | 'outgoing_progress'
  | 'ringing'
  | 'connected'
  | 'ended'
  | 'failed';

export interface CallEvent {
  state: CallStateName;
  reason?: string;
}

declare class LinphoneCallModule extends NativeModule<{ onCall: (e: CallEvent) => void }> {
  startCall(options: StartCallOptions): Promise<void>;
  hangup(): Promise<void>;
  setMute(muted: boolean): Promise<void>;
  setSpeaker(on: boolean): Promise<void>;
  sendDtmf(digit: string): Promise<void>;
}

let nativeModule: LinphoneCallModule | null = null;
function get(): LinphoneCallModule | null {
  if (nativeModule) return nativeModule;
  try {
    nativeModule = requireNativeModule<LinphoneCallModule>('LinphoneCall');
    return nativeModule;
  } catch {
    return null;
  }
}

const noop = () => Promise.resolve();

const api = {
  isAvailable(): boolean {
    return get() !== null;
  },
  startCall(opts: StartCallOptions): Promise<void> {
    const m = get();
    if (!m) return Promise.reject(new Error('Linphone module not available (use a dev/EAS build, not Expo Go)'));
    return m.startCall(opts);
  },
  hangup(): Promise<void> {
    const m = get();
    return m ? m.hangup() : noop();
  },
  setMute(muted: boolean): Promise<void> {
    const m = get();
    return m ? m.setMute(muted) : noop();
  },
  setSpeaker(on: boolean): Promise<void> {
    const m = get();
    return m ? m.setSpeaker(on) : noop();
  },
  sendDtmf(d: string): Promise<void> {
    const m = get();
    return m ? m.sendDtmf(d) : noop();
  },
  addCallListener(cb: (e: CallEvent) => void): () => void {
    const m = get();
    if (!m) return () => {};
    const sub: EventSubscription = m.addListener('onCall', cb);
    return () => sub.remove();
  },
};

export default api;
