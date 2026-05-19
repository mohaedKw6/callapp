import React, { useState, useEffect } from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';
import { Colors, Radii, Spacing } from '../theme/colors';
import { CallState } from '../services/callManager';
import { t } from '../i18n';

const stateLabel = (s, recording) =>
  s === 'connecting' ? t('connecting') :
  s === 'ringing' ? t('ringing') :
  s === 'connected' ? (recording ? t('connectedRecording') : t('connected')) :
  s === 'ended' ? t('callEnded') :
  s === 'failed' ? t('callFailed') : '';

const stateColor = (s) =>
  s === 'connected' ? Colors.success :
  s === 'failed' ? Colors.danger :
  Colors.warning;

const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

const DTMF_KEYS = [
  { d: '1', sub: '' },
  { d: '2', sub: 'ABC' },
  { d: '3', sub: 'DEF' },
  { d: '4', sub: 'GHI' },
  { d: '5', sub: 'JKL' },
  { d: '6', sub: 'MNO' },
  { d: '7', sub: 'PQRS' },
  { d: '8', sub: 'TUV' },
  { d: '9', sub: 'WXYZ' },
  { d: '*', sub: '' },
  { d: '0', sub: '+' },
  { d: '#', sub: '' },
];

export default function CallScreen({
  phone, fromNumber, state, duration, callLimit, muted, speaker,
  onHangup, onMute, onSpeaker, onToggleRecording, recording,
  onSendDtmf, onSetAudioOutput, callManager,
}) {
  const [localRecording, setLocalRecording] = useState(false);
  const [showDtmf, setShowDtmf] = useState(false);
  const [showAudioMenu, setShowAudioMenu] = useState(false);
  const [audioDevices, setAudioDevices] = useState([]);
  const [currentOutput, setCurrentOutput] = useState('earpiece');
  const isRecording = recording ?? localRecording;

  useEffect(() => {
    if (callManager && state === 'connected') {
      callManager.getAudioDevices().then(devices => {
        setAudioDevices(devices || []);
      }).catch(() => {});
    }
  }, [state, callManager]);

  const handleRecord = async () => {
    Haptics.selectionAsync();
    const newState = !isRecording;
    setLocalRecording(newState);
    if (onToggleRecording) {
      try {
        await onToggleRecording(newState);
      } catch {
        setLocalRecording(!newState);
      }
    }
  };

  const handleDtmf = (digit) => {
    Haptics.selectionAsync();
    if (onSendDtmf) {
      onSendDtmf(digit);
    }
  };

  const handleAudioOutput = async (type) => {
    Haptics.selectionAsync();
    setCurrentOutput(type);
    setShowAudioMenu(false);
    if (onSetAudioOutput) {
      onSetAudioOutput(type);
    } else if (callManager) {
      await callManager.setAudioOutput(type);
    }
  };

  const getAudioOutputIcon = () => {
    if (currentOutput === 'bluetooth') return 'bluetooth';
    if (speaker || currentOutput === 'speaker') return 'volume-high';
    return 'volume-medium';
  };

  const getAudioOutputLabel = () => {
    if (currentOutput === 'bluetooth') return t('bluetooth');
    if (speaker || currentOutput === 'speaker') return t('speaker');
    return t('earpiece');
  };

  return (
    <LinearGradient colors={[Colors.bg, '#1a1438', Colors.bg]} style={S.wrap}>
      <SafeAreaView style={S.safe} edges={['top', 'bottom']}>
        <View style={S.top}>
          <Text style={S.label}>{stateLabel(state, isRecording)}</Text>
          <View style={[S.dot, { backgroundColor: stateColor(state) }]} />
          {isRecording && state === 'connected' ? <View style={S.recDot} /> : null}
        </View>

        <View style={S.middle}>
          <View style={S.avatarOuter}>
            <LinearGradient
              colors={[Colors.gradStart, Colors.gradEnd]}
              style={S.avatar}
            >
              <Ionicons name="person" size={64} color="#fff" />
            </LinearGradient>
          </View>
          <Text style={S.phone}>{phone}</Text>
          {state === 'connected' ? (
            <Text style={S.timer}>{fmt(duration)}</Text>
          ) : (
            <Text style={S.timerHint}>
              {state === 'ringing' ? '○ ○ ○' : ''}
            </Text>
          )}
          {fromNumber ? (
            <Text style={S.from}>{t('from')}: {fromNumber}</Text>
          ) : null}
          {callLimit > 0 ? (
            <Text style={S.limit}>{t('maxDuration')}: {Math.floor(callLimit / 60)}:{String(callLimit % 60).padStart(2, '0')}</Text>
          ) : null}
          {isRecording && state === 'connected' ? (
            <View style={S.recBadge}>
              <View style={S.recBadgeDot} />
              <Text style={S.recBadgeTxt}>{t('recording')}</Text>
            </View>
          ) : null}
        </View>

        {/* Audio Output Menu */}
        {showAudioMenu && state === 'connected' ? (
          <View style={S.audioMenu}>
            <Pressable style={[S.audioOption, currentOutput === 'earpiece' && S.audioOptionActive]} onPress={() => handleAudioOutput('earpiece')}>
              <Ionicons name="ear-outline" size={22} color={currentOutput === 'earpiece' ? Colors.primary : Colors.text} />
              <Text style={[S.audioOptionLbl, currentOutput === 'earpiece' && { color: Colors.primary }]}>{t('earpiece')}</Text>
            </Pressable>
            <Pressable style={[S.audioOption, currentOutput === 'speaker' && S.audioOptionActive]} onPress={() => handleAudioOutput('speaker')}>
              <Ionicons name="volume-high" size={22} color={currentOutput === 'speaker' ? Colors.primary : Colors.text} />
              <Text style={[S.audioOptionLbl, currentOutput === 'speaker' && { color: Colors.primary }]}>{t('speaker')}</Text>
            </Pressable>
            <Pressable style={[S.audioOption, currentOutput === 'bluetooth' && S.audioOptionActive]} onPress={() => handleAudioOutput('bluetooth')}
              disabled={!audioDevices.some(d => d.type === 'Bluetooth')}>
              <Ionicons name="bluetooth" size={22} color={
                !audioDevices.some(d => d.type === 'Bluetooth') ? Colors.textDim :
                currentOutput === 'bluetooth' ? Colors.primary : Colors.text
              } />
              <Text style={[S.audioOptionLbl, currentOutput === 'bluetooth' && { color: Colors.primary }]}>{t('bluetooth')}</Text>
            </Pressable>
          </View>
        ) : null}

        {/* DTMF Keypad */}
        {showDtmf && state === 'connected' ? (
          <View style={S.dtmfSection}>
            <View style={S.dtmfGrid}>
              {DTMF_KEYS.map((k) => (
                <Pressable
                  key={k.d}
                  style={({ pressed }) => [S.dtmfKey, pressed && S.dtmfKeyPressed]}
                  onPress={() => handleDtmf(k.d)}
                >
                  <Text style={S.dtmfDigit}>{k.d}</Text>
                  {k.sub ? <Text style={S.dtmfSub}>{k.sub}</Text> : null}
                </Pressable>
              ))}
            </View>
          </View>
        ) : null}

        {/* Actions Row */}
        <View style={S.actionsContainer}>
          {/* Row 1: Mute, Recording, Hangup, Speaker, Keypad */}
          <View style={S.actionsRow}>
            <Pressable
              onPress={() => { Haptics.selectionAsync(); onMute(); }}
              style={({ pressed }) => [S.action, muted && S.actionActive, pressed && S.actionPressed]}
            >
              <Ionicons name={muted ? 'mic-off' : 'mic'} size={24} color={muted ? Colors.danger : Colors.text} />
              <Text style={[S.actionLbl, muted && { color: Colors.danger }]}>{muted ? t('muted') : t('mic')}</Text>
            </Pressable>

            <Pressable
              onPress={() => { Haptics.selectionAsync(); handleRecord(); }}
              style={({ pressed }) => [S.action, isRecording && S.actionRecActive, pressed && S.actionPressed]}
            >
              <Ionicons name={isRecording ? 'stop-circle' : 'radio-button-on-outline'} size={24} color={isRecording ? '#EF4444' : Colors.text} />
              <Text style={[S.actionLbl, isRecording && { color: '#EF4444' }]}>{isRecording ? t('stop') : t('recording')}</Text>
            </Pressable>

            <Pressable
              onPress={() => { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy); onHangup(); }}
              style={({ pressed }) => [S.hangupWrap, pressed && S.actionPressed]}
            >
              <LinearGradient colors={[Colors.danger, Colors.dangerDim]} style={S.hangup}>
                <Ionicons name="call" size={30} color="#fff" style={{ transform: [{ rotate: '135deg' }] }} />
              </LinearGradient>
            </Pressable>

            <Pressable
              onPress={() => { Haptics.selectionAsync(); setShowAudioMenu(!showAudioMenu); setShowDtmf(false); }}
              style={({ pressed }) => [S.action, (speaker || currentOutput !== 'earpiece') && S.actionActive, pressed && S.actionPressed]}
            >
              <Ionicons name={getAudioOutputIcon()} size={24} color={(speaker || currentOutput !== 'earpiece') ? Colors.primary : Colors.text} />
              <Text style={[S.actionLbl, (speaker || currentOutput !== 'earpiece') && { color: Colors.primary }]}>{getAudioOutputLabel()}</Text>
            </Pressable>

            <Pressable
              onPress={() => { Haptics.selectionAsync(); setShowDtmf(!showDtmf); setShowAudioMenu(false); }}
              style={({ pressed }) => [S.action, showDtmf && S.actionActive, pressed && S.actionPressed]}
            >
              <Ionicons name="keypad" size={24} color={showDtmf ? Colors.primary : Colors.text} />
              <Text style={[S.actionLbl, showDtmf && { color: Colors.primary }]}>{t('keypad')}</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const S = StyleSheet.create({
  wrap: { flex: 1 },
  safe: { flex: 1, justifyContent: 'space-between', paddingHorizontal: Spacing.xl },
  top: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    paddingVertical: Spacing.lg,
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
  recDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#EF4444', marginLeft: 4 },
  label: { color: Colors.textMuted, fontSize: 14, fontWeight: '600', letterSpacing: 0.5 },

  middle: { alignItems: 'center', flex: 1, justifyContent: 'center' },
  avatarOuter: {
    padding: 6, borderRadius: Radii.full,
    backgroundColor: 'rgba(124,92,255,0.15)',
    marginBottom: Spacing.xl,
  },
  avatar: {
    width: 140, height: 140, borderRadius: Radii.full,
    justifyContent: 'center', alignItems: 'center',
    shadowColor: Colors.primary, shadowOpacity: 0.5, shadowRadius: 24,
    elevation: 12,
  },
  phone: {
    color: Colors.text, fontSize: 30, fontWeight: '600',
    letterSpacing: 1, marginTop: Spacing.lg,
  },
  timer: {
    color: Colors.success, fontSize: 38, fontWeight: '300',
    marginTop: Spacing.md, fontVariant: ['tabular-nums'],
  },
  timerHint: { color: Colors.textDim, fontSize: 24, marginTop: Spacing.md, letterSpacing: 6 },
  from: { color: Colors.textMuted, fontSize: 13, marginTop: 8, fontFamily: 'monospace' },
  limit: { color: Colors.textDim, fontSize: 11, marginTop: 6 },
  recBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    marginTop: 8, paddingHorizontal: 10, paddingVertical: 4,
    backgroundColor: 'rgba(239,68,68,0.15)', borderRadius: Radii.sm,
  },
  recBadgeDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#EF4444' },
  recBadgeTxt: { color: '#EF4444', fontSize: 12, fontWeight: '700' },

  // Audio output menu
  audioMenu: {
    flexDirection: 'row', justifyContent: 'center', gap: 16,
    paddingVertical: 10, paddingHorizontal: 16,
    backgroundColor: 'rgba(30,24,54,0.9)',
    borderRadius: Radii.lg, marginHorizontal: 20,
    marginBottom: 8,
  },
  audioOption: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: Radii.full,
    backgroundColor: Colors.bgElevated,
    borderWidth: 1, borderColor: Colors.borderSoft,
  },
  audioOptionActive: { borderColor: Colors.primary, backgroundColor: 'rgba(124,92,255,0.15)' },
  audioOptionLbl: { color: Colors.textMuted, fontSize: 12, fontWeight: '600' },

  // DTMF keypad
  dtmfSection: {
    paddingBottom: 8, paddingTop: 4,
  },
  dtmfGrid: {
    flexDirection: 'row', flexWrap: 'wrap',
    justifyContent: 'center', gap: 10,
  },
  dtmfKey: {
    width: 62, height: 62, borderRadius: Radii.full,
    backgroundColor: 'rgba(30,24,54,0.8)',
    justifyContent: 'center', alignItems: 'center',
    borderWidth: 1, borderColor: Colors.borderSoft,
  },
  dtmfKeyPressed: {
    backgroundColor: Colors.card,
    transform: [{ scale: 0.93 }],
  },
  dtmfDigit: { color: Colors.text, fontSize: 26, fontWeight: '500', lineHeight: 28 },
  dtmfSub: { color: Colors.textDim, fontSize: 8, fontWeight: '700', letterSpacing: 1.2, marginTop: 1 },

  // Actions - improved layout
  actionsContainer: {
    paddingBottom: Spacing.lg, paddingTop: Spacing.md,
  },
  actionsRow: {
    flexDirection: 'row', justifyContent: 'space-around', alignItems: 'center',
    paddingHorizontal: Spacing.sm,
  },
  action: {
    width: 60, height: 60, borderRadius: Radii.full,
    backgroundColor: Colors.bgElevated,
    justifyContent: 'center', alignItems: 'center',
    borderWidth: 1, borderColor: Colors.border,
  },
  actionActive: { backgroundColor: Colors.card },
  actionRecActive: {
    backgroundColor: 'rgba(239,68,68,0.12)',
    borderColor: 'rgba(239,68,68,0.4)',
  },
  actionPressed: { transform: [{ scale: 0.92 }] },
  actionLbl: { color: Colors.textMuted, fontSize: 9, fontWeight: '600', marginTop: 2 },

  hangupWrap: { borderRadius: Radii.full, overflow: 'hidden', elevation: 10 },
  hangup: {
    width: 72, height: 72, borderRadius: Radii.full,
    justifyContent: 'center', alignItems: 'center',
    shadowColor: Colors.danger, shadowOpacity: 0.6, shadowRadius: 20,
  },
});
