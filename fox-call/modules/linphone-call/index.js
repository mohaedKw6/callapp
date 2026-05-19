import { NativeModule, requireNativeModule, EventSubscription } from 'expo-modules-core';

let nativeModule = null;
function get() {
  if (nativeModule) return nativeModule;
  try {
    nativeModule = requireNativeModule('LinphoneCall');
    return nativeModule;
  } catch {
    return null;
  }
}

const noop = () => Promise.resolve();

const api = {
  isAvailable() {
    return get() !== null;
  },
  startCall(opts) {
    const m = get();
    if (!m) return Promise.reject(new Error('Linphone module not available (use a dev/EAS build, not Expo Go)'));
    return m.startCall(opts);
  },
  hangup() {
    const m = get();
    return m ? m.hangup() : noop();
  },
  setMute(muted) {
    const m = get();
    return m ? m.setMute(muted) : noop();
  },
  setSpeaker(on) {
    const m = get();
    return m ? m.setSpeaker(on) : noop();
  },
  setAudioOutput(outputType) {
    const m = get();
    return m ? m.setAudioOutput(outputType) : noop();
  },
  getAudioDevices() {
    const m = get();
    if (!m) return Promise.resolve([]);
    return m.getAudioDevices();
  },
  sendDtmf(d) {
    const m = get();
    return m ? m.sendDtmf(d) : noop();
  },
  addCallListener(cb) {
    const m = get();
    if (!m) return () => {};
    const sub = m.addListener('onCall', cb);
    return () => sub.remove();
  },
};

export default api;
