import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';
import { Colors, Radii, Spacing } from '../theme/colors';
import { CallState } from '../services/callManager';

interface Props {
  phone: string;
  fromNumber: string;
  state: CallState;
  duration: number;
  callLimit: number;
  muted: boolean;
  speaker: boolean;
  onHangup: () => void;
  onMute: () => void;
  onSpeaker: () => void;
}

const stateLabel = (s: CallState) =>
  s === 'connecting' ? 'جاري الاتصال...' :
  s === 'ringing' ? 'جاري الرنين...' :
  s === 'connected' ? 'متصل الآن' :
  s === 'ended' ? 'انتهت المكالمة' :
  s === 'failed' ? 'فشلت المكالمة' : '';

const stateColor = (s: CallState) =>
  s === 'connected' ? Colors.success :
  s === 'failed' ? Colors.danger :
  Colors.warning;

const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

export default function CallScreen({
  phone, fromNumber, state, duration, callLimit, muted, speaker, onHangup, onMute, onSpeaker,
}: Props) {
  return (
    <LinearGradient colors={[Colors.bg, '#1a1438', Colors.bg]} style={S.wrap}>
      <SafeAreaView style={S.safe} edges={['top', 'bottom']}>
        <View style={S.top}>
          <Text style={S.label}>{stateLabel(state)}</Text>
          <View style={[S.dot, { backgroundColor: stateColor(state) }]} />
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
            <Text style={S.from}>من: {fromNumber}</Text>
          ) : null}
          {callLimit > 0 ? (
            <Text style={S.limit}>الحد الأقصى: {Math.floor(callLimit / 60)}:{String(callLimit % 60).padStart(2, '0')}</Text>
          ) : null}
        </View>

        <View style={S.actions}>
          <Pressable
            onPress={() => { Haptics.selectionAsync(); onMute(); }}
            style={({ pressed }) => [S.action, muted && S.actionActive, pressed && S.actionPressed]}
          >
            <Ionicons name={muted ? 'mic-off' : 'mic'} size={26} color={muted ? Colors.danger : Colors.text} />
            <Text style={[S.actionLbl, muted && { color: Colors.danger }]}>{muted ? 'مكتوم' : 'مايك'}</Text>
          </Pressable>

          <Pressable
            onPress={() => { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy); onHangup(); }}
            style={({ pressed }) => [S.hangupWrap, pressed && S.actionPressed]}
          >
            <LinearGradient colors={[Colors.danger, Colors.dangerDim]} style={S.hangup}>
              <Ionicons name="call" size={32} color="#fff" style={{ transform: [{ rotate: '135deg' }] }} />
            </LinearGradient>
          </Pressable>

          <Pressable
            onPress={() => { Haptics.selectionAsync(); onSpeaker(); }}
            style={({ pressed }) => [S.action, speaker && S.actionActive, pressed && S.actionPressed]}
          >
            <Ionicons name={speaker ? 'volume-high' : 'volume-medium'} size={26} color={speaker ? Colors.primary : Colors.text} />
            <Text style={[S.actionLbl, speaker && { color: Colors.primary }]}>سماعة</Text>
          </Pressable>
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

  actions: {
    flexDirection: 'row', justifyContent: 'space-around', alignItems: 'center',
    paddingBottom: Spacing.xl, paddingTop: Spacing.xl,
  },
  action: {
    width: 72, height: 72, borderRadius: Radii.full,
    backgroundColor: Colors.bgElevated,
    justifyContent: 'center', alignItems: 'center',
    borderWidth: 1, borderColor: Colors.border,
  },
  actionActive: { backgroundColor: Colors.card },
  actionPressed: { transform: [{ scale: 0.92 }] },
  actionLbl: { color: Colors.textMuted, fontSize: 10, fontWeight: '600', marginTop: 2 },

  hangupWrap: { borderRadius: Radii.full, overflow: 'hidden', elevation: 10 },
  hangup: {
    width: 84, height: 84, borderRadius: Radii.full,
    justifyContent: 'center', alignItems: 'center',
    shadowColor: Colors.danger, shadowOpacity: 0.6, shadowRadius: 20,
  },
});
