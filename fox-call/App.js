import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, Alert, PermissionsAndroid, Platform, ActivityIndicator } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import { NativeModules } from 'react-native';
import mobileAds, { InterstitialAd, AdEventType, TestIds } from 'react-native-google-mobile-ads';
import Constants from 'expo-constants';

import TokenScreen from './screens/TokenScreen';
import DialerScreen from './screens/DialerScreen';
import CallScreen from './screens/CallScreen';
import CallHistoryScreen from './screens/CallHistoryScreen';
import UpdateScreen from './screens/UpdateScreen';
import { FoxApi } from './services/api';
import { CallManager, CallState } from './services/callManager';
import { Colors } from './theme/colors';
import { initLang, t, toggleLang, getLang, isRTL } from './i18n';


// ─── App Version ────────────────────────────────────────────────────────────
const APP_VERSION_CODE = Constants.expoConfig?.android?.versionCode
  || Constants.manifest?.android?.versionCode
  || 15;

// ─── AdMob Configuration ──────────────────────────────────────────────────
const AD_UNIT_ID = __DEV__
  ? TestIds.INTERSTITIAL
  : 'ca-app-pub-6875688805927337/6338779882';

let interstitialAd = null;
let isAdReady = false;

function initAdMob() {
  try {
    mobileAds().initialize().then(() => {
      console.log('[AdMob] Initialized');
      loadInterstitialAd();
    });
  } catch (e) {
    console.log('[AdMob] Init failed:', e?.message);
  }
}

function loadInterstitialAd() {
  try {
    if (interstitialAd) {
      interstitialAd.removeAllListeners();
    }
    interstitialAd = InterstitialAd.createForAdRequest(AD_UNIT_ID);
    interstitialAd.addAdEventListener(AdEventType.LOADED, () => {
      isAdReady = true;
      console.log('[AdMob] Interstitial ad loaded');
    });
    interstitialAd.addAdEventListener(AdEventType.CLOSED, () => {
      isAdReady = false;
      loadInterstitialAd(); // preload next ad
    });
    interstitialAd.addAdEventListener(AdEventType.ERROR, (e) => {
      console.log('[AdMob] Ad error:', e?.message);
    });
    interstitialAd.load();
  } catch (e) {
    console.log('[AdMob] Load failed:', e?.message);
  }
}

function showInterstitialAd() {
  try {
    if (interstitialAd && isAdReady) {
      interstitialAd.show();
      isAdReady = false;
    } else {
      loadInterstitialAd(); // try to load for next time
    }
  } catch (e) {
    console.log('[AdMob] Show failed:', e?.message);
  }
}

// ─── Version Check (unauthenticated) ────────────────────────────────────────

async function checkAppVersion(serverUrl) {
  try {
    const url = `${serverUrl}/api/app-version?vc=${APP_VERSION_CODE}`;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(timer);
    if (!res.ok) return null;
    const data = await res.json();
    return data;
  } catch (e) {
    console.log('[VersionCheck] Failed:', e?.message);
    return null;
  }
}

const TOKEN_KEY = 'foxcall_token_v2';
const JWT_ACCESS_KEY = 'foxcall_jwt_access_v1';
const JWT_REFRESH_KEY = 'foxcall_jwt_refresh_v1';
const DEVICE_KEY = 'foxcall_device_id';


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

  // Force update state
  const [updateInfo, setUpdateInfo] = useState(null);

  // Call state
  const [callState, setCallState] = useState('idle');
  const [callDuration, setCallDuration] = useState(0);
  const [callFrom, setCallFrom] = useState('');
  const [callLimit, setCallLimit] = useState(0);
  const [muted, setMuted] = useState(false);
  const [speaker, setSpeaker] = useState(false);
  const [recording, setRecording] = useState(false);

  const apiRef = useRef(null);
  const cmRef = useRef(null);

  useEffect(() => {
    initAdMob();
    bootstrap();
    return () => { cmRef.current?.destroy(); };
  }, []);

  const bootstrap = async () => {
    try {
      await initLang();
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

      // ── Version Check ────────────────────────────────────────
      // Always check version, even without a saved token.
      // Use a default server URL if no token is available.
      const serverUrlForCheck = (() => {
        if (tok) {
          const tokenInfo = FoxApi.decodeTokenOnly(tok);
          if (tokenInfo?.serverUrl) return tokenInfo.serverUrl;
        }
        // Fallback: use the known server URL
        return 'https://eaiupvh6.up.railway.app';
      })();

      const vData = await checkAppVersion(serverUrlForCheck);
      if (vData && vData.force_update) {
        // App is too old — show force update screen
        setUpdateInfo(vData);
        setScreen('update');
        return; // STOP — do not proceed to login
      }

      if (tok) {
        const ok = await connect(tok, did);
        if (ok) {
          // Pre-fetch balance/me data on open
          prefetchUserData();
          return;
        }
      }
    } catch {}
    setScreen('token');
  };

  const requestMicPermission = async () => {
    if (Platform.OS !== 'android') return true;
    const r = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
      {
        title: t('micPermission'),
        message: t('micMsg'),
        buttonPositive: t('allow'),
        buttonNegative: t('deny'),
      }
    );
    return r === PermissionsAndroid.RESULTS.GRANTED;
  };



  const connect = async (rawToken, deviceId) => {
    const did = deviceId || (await SecureStore.getItemAsync(DEVICE_KEY)) || genDeviceId();
    const api = FoxApi.fromToken(rawToken, did);
    if (!api) throw new Error('التوكن غير صحيح');
    apiRef.current = api;

    // ── Version check before login (when entering a new token) ──
    const vData = await checkAppVersion(api.getServerUrl());
    if (vData && vData.force_update) {
      setUpdateInfo(vData);
      setScreen('update');
      return false;
    }

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
      return true;
    } catch (e) {
      const msg = e?.message || 'فشل تسجيل الدخول';
      // If token was changed/revoked, force logout and go to token screen
      if (e?.isTokenChanged || msg.includes('تغيير التوكن') || msg.includes('قديم') || msg.includes('إلغاؤه') || msg.includes('token_changed') || msg.includes('token_revoked')) {
        await forceLogout();
        throw new Error('تم تغيير التوكن برجاء ادخال التوكن الجديد');
      }
      throw new Error(msg);
    }
  };

  const handleConnect = async (token) => { await connect(token); };

  const refreshMe = async () => {
    if (!apiRef.current) return;
    try {
      const me = await apiRef.current.getMe();
      setUser(me);
    } catch (e) {
      if (e?.isTokenChanged || (e?.message && (e.message.includes('token_changed') || e.message.includes('تغيير التوكن')))) {
        Alert.alert(t('alert'), e?.message || t('tokenChanged'), [
          { text: t('allow'), onPress: forceLogout },
        ]);
      }
    }
  };

  // Pre-fetch user data on app open (background, non-blocking)
  const prefetchUserData = () => {
    if (!apiRef.current) return;
    apiRef.current.getMe()
      .then(me => setUser(me))
      .catch(() => {});
  };

  const handleCall = async () => {
    if (!phone || !cmRef.current) return;
    // Check balance before allowing call
    const callCost = user?.cost || 0.20;
    const currentBalance = user?.balance ?? 0;
    if (currentBalance < callCost) {
      Alert.alert(t('insufficientBalance'), t('insufficientMsg', {balance: currentBalance.toFixed(2), cost: callCost.toFixed(2)}));
      return;
    }
    const ok = await requestMicPermission();
    if (!ok) {
      Alert.alert(t('alert'), t('micRequired'));
      return;
    }
    const cm = cmRef.current;
    cm.on({
      onState: setCallState,
      onDuration: setCallDuration,
      onError: (m) => Alert.alert(t('failed'), m),
      onEnd: (callResult) => {
        setTimeout(() => {
          setScreen('dialer');
          setCallState('idle');
          setCallDuration(0);
          setCallFrom('');
          setMuted(false);
          setSpeaker(false);
          setRecording(false);
          // Auto-fetch after call ends to refresh balance
          refreshMe();
          showInterstitialAd();
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
      // If token was changed or session revoked, force logout immediately
      if (e?.isTokenChanged || (e?.message && (e.message.includes('token_changed') || e.message.includes('تغيير التوكن') || e.message.includes('session_revoked') || e.message.includes('جهاز آخر')))) {
        Alert.alert(t('alert'), e?.message || t('tokenChanged'), [
          { text: t('allow'), onPress: forceLogout },
        ]);
      }
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

  const forceLogout = async () => {
    cmRef.current?.destroy();
    apiRef.current = null;
    cmRef.current = null;
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    await SecureStore.deleteItemAsync(JWT_ACCESS_KEY);
    await SecureStore.deleteItemAsync(JWT_REFRESH_KEY);
    setUser(null);
    setPhone('');
    setScreen('token');
  };

  const handleLogout = async () => {
    Alert.alert(t('confirm'), t('wantLogout'), [
      { text: t('cancel'), style: 'cancel' },
      {
        text: t('exit'), style: 'destructive', onPress: forceLogout,
      },
    ]);
  };

  return (
    <SafeAreaProvider>
      <StatusBar style="light" backgroundColor={Colors.bg} />
      {screen === 'loading' && (
        <View style={S.loading}>
          <ActivityIndicator size="large" color={Colors.primary} />
          <Text style={S.loadingTxt}>{t('loading')}</Text>
        </View>
      )}
      {screen === 'update' && (
        <UpdateScreen
          downloadUrl={updateInfo?.download_url}
          messageAr={updateInfo?.update_message_ar}
          latestVersion={updateInfo?.latest_version}
          apkSize={updateInfo?.apk_size}
        />
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
          onCallHistory={handleCallHistory}
          onToggleLang={toggleLang}
          currentLang={getLang()}
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
          onSendDtmf={(d) => cmRef.current?.sendDtmf(d)}
          onSetAudioOutput={(t) => cmRef.current?.setAudioOutput(t)}
          callManager={cmRef.current}
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
