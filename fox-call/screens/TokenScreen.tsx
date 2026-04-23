import React, { useState } from 'react';
import {
  View, Text, TextInput, Pressable, StyleSheet, ActivityIndicator,
  KeyboardAvoidingView, Platform, ScrollView, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { Colors, Radii, Spacing } from '../theme/colors';
import { decodeFoxToken } from '../services/foxToken';

interface Props {
  onConnect: (token: string) => Promise<void>;
}

export default function TokenScreen({ onConnect }: Props) {
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = token.trim().length > 20 && /^\d+:/.test(token.trim());

  const submit = async () => {
    setError(null);
    const t = token.trim();
    if (!t) return;
    const info = decodeFoxToken(t);
    if (!info) {
      setError('التوكن غير صحيح. تأكد إنك نسخته كامل من البوت.');
      return;
    }
    setLoading(true);
    try {
      await onConnect(t);
    } catch (e: any) {
      setError(e?.message || 'فشل الاتصال بالسيرفر');
    } finally {
      setLoading(false);
    }
  };

  return (
    <LinearGradient colors={[Colors.bg, Colors.bgElevated]} style={S.wrap}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={S.flex}
      >
        <ScrollView contentContainerStyle={S.scroll} keyboardShouldPersistTaps="handled">
          <View style={S.header}>
            <LinearGradient
              colors={[Colors.gradStart, Colors.gradEnd]}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={S.logo}
            >
              <Ionicons name="call" size={42} color="#fff" />
            </LinearGradient>
            <Text style={S.title}>Fox Call</Text>
            <Text style={S.subtitle}>مكالمات صوتية مباشرة وآمنة</Text>
          </View>

          <View style={S.card}>
            <View style={S.labelRow}>
              <Ionicons name="key-outline" size={16} color={Colors.textMuted} />
              <Text style={S.label}>توكن الدخول</Text>
            </View>
            <TextInput
              style={[S.input, error && S.inputErr]}
              value={token}
              onChangeText={(v) => { setToken(v); setError(null); }}
              placeholder="الصق التوكن هنا..."
              placeholderTextColor={Colors.textDim}
              multiline
              autoCapitalize="none"
              autoCorrect={false}
              textAlignVertical="top"
              editable={!loading}
            />
            {error ? (
              <View style={S.errBox}>
                <Ionicons name="alert-circle" size={16} color={Colors.danger} />
                <Text style={S.errText}>{error}</Text>
              </View>
            ) : null}

            <Pressable
              onPress={submit}
              disabled={!valid || loading}
              style={({ pressed }) => [
                S.btnWrap,
                (!valid || loading) && S.btnDisabled,
                pressed && S.btnPressed,
              ]}
            >
              <LinearGradient
                colors={[Colors.gradStart, Colors.gradEnd]}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 0 }}
                style={S.btn}
              >
                {loading ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Text style={S.btnTxt}>دخول</Text>
                    <Ionicons name="arrow-back" size={18} color="#fff" />
                  </>
                )}
              </LinearGradient>
            </Pressable>
          </View>

          <View style={S.tipBox}>
            <Ionicons name="information-circle" size={14} color={Colors.textMuted} />
            <Text style={S.tip}>
              اطلب التوكن من البوت في تيليجرام بأمر  /token
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </LinearGradient>
  );
}

const S = StyleSheet.create({
  wrap: { flex: 1 },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, padding: Spacing.xl, justifyContent: 'center' },
  header: { alignItems: 'center', marginBottom: Spacing.xxl },
  logo: {
    width: 92, height: 92, borderRadius: Radii.full,
    justifyContent: 'center', alignItems: 'center',
    marginBottom: Spacing.lg,
    shadowColor: Colors.primary,
    shadowOpacity: 0.5, shadowRadius: 20, shadowOffset: { width: 0, height: 8 },
    elevation: 12,
  },
  title: { color: Colors.text, fontSize: 30, fontWeight: '800', letterSpacing: 0.5 },
  subtitle: { color: Colors.textMuted, fontSize: 14, marginTop: 6 },

  card: {
    backgroundColor: Colors.card,
    borderRadius: Radii.xl,
    padding: Spacing.xl,
    borderWidth: 1, borderColor: Colors.border,
  },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 10 },
  label: { color: Colors.textMuted, fontSize: 13, fontWeight: '600' },
  input: {
    backgroundColor: Colors.bg,
    borderWidth: 1, borderColor: Colors.border,
    borderRadius: Radii.lg,
    padding: Spacing.lg,
    color: Colors.text,
    fontSize: 14, minHeight: 110,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  inputErr: { borderColor: Colors.danger },
  errBox: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    marginTop: 10, padding: 10, borderRadius: Radii.md,
    backgroundColor: 'rgba(239,68,68,0.1)',
  },
  errText: { color: Colors.danger, fontSize: 13, flex: 1 },

  btnWrap: { borderRadius: Radii.lg, overflow: 'hidden', marginTop: Spacing.lg },
  btnDisabled: { opacity: 0.4 },
  btnPressed: { opacity: 0.85 },
  btn: {
    flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 10,
    paddingVertical: 16,
  },
  btnTxt: { color: '#fff', fontSize: 17, fontWeight: '700' },

  tipBox: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    marginTop: Spacing.xl,
  },
  tip: { color: Colors.textMuted, fontSize: 12 },
});
