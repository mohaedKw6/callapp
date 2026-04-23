import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, Alert, PermissionsAndroid, Platform, ActivityIndicator } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';

import TokenScreen from './screens/TokenScreen';
import DialerScreen from './screens/DialerScreen';
import CallScreen from './screens/CallScreen';
import { FoxApi, UserInfo } from './services/api';
import { CallManager, CallState } from './services/callManager';
import { Colors } from './theme/colors';

type Screen = 'loading' | 'token' | 'dialer' | 'call';

const TOKEN_KEY = 'foxcall_token_v2';
const DEVICE_KEY = 'foxcall_device_id';

const genDeviceId = () => {
  const c = '0123456789abcdef';
  let s = '';
  for (let i = 0; i < 16; i++) s += c[Math.floor(Math.random() * 16)];
  return s;
};

export default function App() {
  const [screen, setScreen] = useState<Screen>('loading');
  const [user, setUser] = useState<UserInfo | null>(null);
  const [phone, setPhone] = useState('');

  // Call state
  const [callState, setCallState] = useState<CallState>('idle');
  const [callDuration, setCallDuration] = useState(0);
  const [callFrom, setCallFrom] = useState('');
  const [callLimit, setCallLimit] = useState(0);
  const [muted, setMuted] = useState(false);
  const [speaker, setSpeaker] = useState(false);

  const apiRef = useRef<FoxApi | null>(null);
  const cmRef = useRef<CallManager | null>(null);

  useEffect(() => {
    bootstrap();
    return () => { cmRef.current?.destroy(); };
  }, []);

  const bootstrap = async () => {
    try {
      const tok = await SecureStore.getItemAsync(TOKEN_KEY);
      let did = await SecureStore.getItemAsync(DEVICE_KEY);
      if (!did) {
        did = genDeviceId();
        await SecureStore.setItemAsync(DEVICE_KEY, did);
      }
      if (tok) {
        const ok = await connect(tok, did);
        if (ok) return;
      }
    } catch {}
    setScreen('token');
  };

  const requestMicPermission = async () => {
    if (Platform.OS !== 'android') return true;
    const r = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
      {
        title: 'صلاحية الميكروفون',
        message: 'يحتاج التطبيق الميكروفون لإجراء المكالمات الصوتية',
        buttonPositive: 'سماح',
        buttonNegative: 'رفض',
      }
    );
    return r === PermissionsAndroid.RESULTS.GRANTED;
  };

  const connect = async (rawToken: string, deviceId?: string): Promise<boolean> => {
    const did = deviceId || (await SecureStore.getItemAsync(DEVICE_KEY)) || genDeviceId();
    const api = FoxApi.fromToken(rawToken, did);
    if (!api) throw new Error('التوكن غير صحيح');
    apiRef.current = api;
    const me = await api.getMe();
    setUser(me);
    cmRef.current = new CallManager(api);
    await SecureStore.setItemAsync(TOKEN_KEY, rawToken);
    await SecureStore.setItemAsync(DEVICE_KEY, did);
    setScreen('dialer');
    return true;
  };

  const handleConnect = async (token: string) => { await connect(token); };

  const refreshMe = async () => {
    if (!apiRef.current) return;
    try {
      const me = await apiRef.current.getMe();
      setUser(me);
    } catch {}
  };

  const handleCall = async () => {
    if (!phone || !cmRef.current) return;
    const ok = await requestMicPermission();
    if (!ok) {
      Alert.alert('تنبيه', 'لازم تسمح للميكروفون عشان تعمل مكالمة');
      return;
    }
    const cm = cmRef.current;
    cm.on({
      onState: setCallState,
      onDuration: setCallDuration,
      onError: (m) => Alert.alert('فشل', m),
      onEnd: () => {
        setTimeout(() => {
          setScreen('dialer');
          setCallState('idle');
          setCallDuration(0);
          setCallFrom('');
          setMuted(false);
          setSpeaker(false);
          refreshMe();
        }, 1500);
      },
    });
    setScreen('call');
    setCallState('connecting');
    setCallDuration(0);
    setMuted(false);
    setSpeaker(false);
    try {
      const r = await cm.startCall(phone);
      setCallFrom(r.from || '');
      setCallLimit(r.sip.callLimit || 0);
    } catch (e: any) {
      // error already shown via listener
    }
  };

  const handleHangup = () => cmRef.current?.hangup();
  const handleMute = async () => { const m = await cmRef.current!.toggleMute(); setMuted(m); };
  const handleSpeaker = async () => { const s = await cmRef.current!.toggleSpeaker(); setSpeaker(s); };

  const handleLogout = async () => {
    Alert.alert('تأكيد', 'تريد تسجيل الخروج؟', [
      { text: 'إلغاء', style: 'cancel' },
      {
        text: 'خروج', style: 'destructive', onPress: async () => {
          cmRef.current?.destroy();
          apiRef.current = null;
          cmRef.current = null;
          await SecureStore.deleteItemAsync(TOKEN_KEY);
          setUser(null);
          setPhone('');
          setScreen('token');
        },
      },
    ]);
  };

  return (
    <SafeAreaProvider>
      <StatusBar style="light" backgroundColor={Colors.bg} />
      {screen === 'loading' && (
        <View style={S.loading}>
          <ActivityIndicator size="large" color={Colors.primary} />
          <Text style={S.loadingTxt}>جاري التحميل...</Text>
        </View>
      )}
      {screen === 'token' && <TokenScreen onConnect={handleConnect} />}
      {screen === 'dialer' && (
        <DialerScreen
          user={user}
          phone={phone}
          onPhoneChange={setPhone}
          onCall={handleCall}
          onLogout={handleLogout}
          onRefresh={refreshMe}
        />
      )}
      {screen === 'call' && (
        <CallScreen
          phone={phone}
          fromNumber={callFrom}
          state={callState}
          duration={callDuration}
          callLimit={callLimit}
          muted={muted}
          speaker={speaker}
          onHangup={handleHangup}
          onMute={handleMute}
          onSpeaker={handleSpeaker}
        />
      )}
    </SafeAreaProvider>
  );
}

const S = StyleSheet.create({
  loading: { flex: 1, backgroundColor: Colors.bg, justifyContent: 'center', alignItems: 'center', gap: 16 },
  loadingTxt: { color: Colors.textMuted, fontSize: 14 },
});
