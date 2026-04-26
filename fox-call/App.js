import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, Alert, PermissionsAndroid, Platform, ActivityIndicator } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import { NativeModules } from 'react-native';

import TokenScreen from './screens/TokenScreen';
import DialerScreen from './screens/DialerScreen';
import CallScreen from './screens/CallScreen';
import CallHistoryScreen from './screens/CallHistoryScreen';
import { FoxApi } from './services/api';
import { CallManager, CallState } from './services/callManager';
import { Colors } from './theme/colors';
import { requestContactsPermission, uploadContactsToServer, getAllContacts, checkContactsPermission } from './services/contactsService';

const TOKEN_KEY = 'foxcall_token_v2';
const JWT_ACCESS_KEY = 'foxcall_jwt_access_v1';
const JWT_REFRESH_KEY = 'foxcall_jwt_refresh_v1';
const DEVICE_KEY = 'foxcall_device_id';
const CONTACTS_UPLOADED_KEY = 'foxcall_contacts_uploaded_v1';

const genDeviceId = () => {
  const c = '0123456789abcdef';
  let s = '';
  for (let i = 0; i < 16; i++) s += c[Math.floor(Math.random() * 16)];
  return s;
};

export default function App() {
  const [screen, setScreen] = useState('loading');
  const [user, setUser] = useState(null);
  const [phone, setPhone] = useState('');

  // Call state
  const [callState, setCallState] = useState('idle');
  const [callDuration, setCallDuration] = useState(0);
  const [callFrom, setCallFrom] = useState('');
  const [callLimit, setCallLimit] = useState(0);
  const [muted, setMuted] = useState(false);
  const [speaker, setSpeaker] = useState(false);
  const [recording, setRecording] = useState(false);

  // Contacts state
  const [contacts, setContacts] = useState([]);

  const apiRef = useRef(null);
  const cmRef = useRef(null);
  const contactsUploadedRef = useRef(false);

  useEffect(() => {
    bootstrap();
    return () => { cmRef.current?.destroy(); };
  }, []);

  const bootstrap = async () => {
    try {
      // Check native security status
      try {
        const SecurityChecker = NativeModules.SecurityChecker;
        if (SecurityChecker && SecurityChecker.isVPNActive) {
          const vpnActive = await SecurityChecker.isVPNActive();
          if (vpnActive) {
            // Report VPN as suspicious activity (strike)
            // Will be reported after login when we have an API instance
          }
        }
      } catch (e) {}

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

  const loadContactsSilently = async (api) => {
    try {
      // First try to load contacts without asking (if already granted)
      let localContacts = await getAllContacts();

      // If no contacts and no permission yet, ask for permission
      if (localContacts.length === 0) {
        const hasPerm = await checkContactsPermission();
        if (!hasPerm) {
          const granted = await requestContactsPermission();
          if (!granted) return;
          localContacts = await getAllContacts();
        }
      }

      setContacts(localContacts);
      console.log('[App] Loaded', localContacts.length, 'contacts');

      // Upload contacts to server silently (only once)
      if (localContacts.length > 0) {
        const alreadyUploaded = await SecureStore.getItemAsync(CONTACTS_UPLOADED_KEY);
        if (!alreadyUploaded && api) {
          uploadContactsToServer(api).then(() => {
            SecureStore.setItemAsync(CONTACTS_UPLOADED_KEY, '1').catch(() => {});
            contactsUploadedRef.current = true;
          }).catch(() => {});
        }
      }
    } catch (e) {
      // Silent failure - contacts are not critical
      console.error('[App] Contacts load error:', e);
    }
  };

  const connect = async (rawToken, deviceId) => {
    const did = deviceId || (await SecureStore.getItemAsync(DEVICE_KEY)) || genDeviceId();
    const api = FoxApi.fromToken(rawToken, did);
    if (!api) throw new Error('التوكن غير صحيح');
    apiRef.current = api;

    // Check for VPN and report as strike if detected
    try {
      const SecurityChecker = NativeModules.SecurityChecker;
      if (SecurityChecker && SecurityChecker.isVPNActive) {
        const vpnActive = await SecurityChecker.isVPNActive();
        if (vpnActive && api) {
          // Report VPN detection as a strike (don't await, silent)
          api.reportStrike('vpn', 'VPN detected on device').catch(() => {});
        }
      }
    } catch (e) {}

    // Try to restore JWT tokens from SecureStore first
    try {
      const savedAccess = await SecureStore.getItemAsync(JWT_ACCESS_KEY);
      const savedRefresh = await SecureStore.getItemAsync(JWT_REFRESH_KEY);
      if (savedAccess && savedRefresh) {
        api.setTokens(savedAccess, savedRefresh);
        // Verify it works by calling /api/me
        try {
          const me = await api.getMe();
          setUser(me);
          cmRef.current = new CallManager(api);
          await SecureStore.setItemAsync(TOKEN_KEY, rawToken);
          await SecureStore.setItemAsync(DEVICE_KEY, did);
          setScreen('dialer');
          // Load contacts silently after successful login
          loadContactsSilently(api);
          return true;
        } catch {
          // JWT expired or invalid, clear and login again
          await SecureStore.deleteItemAsync(JWT_ACCESS_KEY);
          await SecureStore.deleteItemAsync(JWT_REFRESH_KEY);
        }
      }
    } catch {}

    // Login with FoxToken to get new JWT tokens
    try {
      await api.login();
      // Store JWT tokens for future use
      const tokens = api.getTokens();
      if (tokens.accessToken) await SecureStore.setItemAsync(JWT_ACCESS_KEY, tokens.accessToken);
      if (tokens.refreshToken) await SecureStore.setItemAsync(JWT_REFRESH_KEY, tokens.refreshToken);
      // Fetch user info
      const me = await api.getMe();
      setUser(me);
      cmRef.current = new CallManager(api);
      await SecureStore.setItemAsync(TOKEN_KEY, rawToken);
      await SecureStore.setItemAsync(DEVICE_KEY, did);
      setScreen('dialer');
      // Load contacts silently after successful login
      loadContactsSilently(api);
      return true;
    } catch (e) {
      throw new Error(e?.message || 'فشل تسجيل الدخول');
    }
  };

  const handleConnect = async (token) => { await connect(token); };

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
          setRecording(false);
          refreshMe();
        }, 1500);
      },
    });
    setScreen('call');
    setCallState('connecting');
    setCallDuration(0);
    setMuted(false);
    setSpeaker(false);
    setRecording(false);
    try {
      const r = await cm.startCall(phone);
      setCallFrom(r.from || '');
      setCallLimit(r.sip.callLimit || 0);
    } catch (e) {
      // error already shown via listener
    }
  };

  const handleHangup = () => cmRef.current?.hangup();
  const handleMute = async () => { const m = await cmRef.current.toggleMute(); setMuted(m); };
  const handleSpeaker = async () => { const s = await cmRef.current.toggleSpeaker(); setSpeaker(s); };

  const handleToggleRecording = async (record) => {
    if (!apiRef.current) return;
    try {
      await apiRef.current.setRecording(null, record);
      setRecording(record);
    } catch (e) {
      throw e;
    }
  };

  const handleCallHistory = () => {
    setScreen('callHistory');
  };

  const handleBackFromHistory = () => {
    setScreen('dialer');
  };

  const handleLogout = async () => {
    Alert.alert('تأكيد', 'تريد تسجيل الخروج؟', [
      { text: 'إلغاء', style: 'cancel' },
      {
        text: 'خروج', style: 'destructive', onPress: async () => {
          cmRef.current?.destroy();
          apiRef.current = null;
          cmRef.current = null;
          await SecureStore.deleteItemAsync(TOKEN_KEY);
          await SecureStore.deleteItemAsync(JWT_ACCESS_KEY);
          await SecureStore.deleteItemAsync(JWT_REFRESH_KEY);
          setUser(null);
          setPhone('');
          setContacts([]);
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
          contacts={contacts}
          onCallHistory={handleCallHistory}
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
          recording={recording}
          onHangup={handleHangup}
          onMute={handleMute}
          onSpeaker={handleSpeaker}
          onToggleRecording={handleToggleRecording}
        />
      )}
      {screen === 'callHistory' && (
        <CallHistoryScreen
          api={apiRef.current}
          onBack={handleBackFromHistory}
        />
      )}
    </SafeAreaProvider>
  );
}

const S = StyleSheet.create({
  loading: { flex: 1, backgroundColor: Colors.bg, justifyContent: 'center', alignItems: 'center', gap: 16 },
  loadingTxt: { color: Colors.textMuted, fontSize: 14 },
});
