import React from 'react';
import { View, Text, Pressable, StyleSheet, RefreshControl, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';
import Numpad, { DeleteKey } from '../components/Numpad';
import { Colors, Radii, Spacing } from '../theme/colors';
import { UserInfo } from '../services/api';

interface Props {
  user: UserInfo | null;
  phone: string;
  onPhoneChange: (v: string) => void;
  onCall: () => void;
  onLogout: () => void;
  onRefresh: () => Promise<void>;
}

export default function DialerScreen({ user, phone, onPhoneChange, onCall, onLogout, onRefresh }: Props) {
  const [refreshing, setRefreshing] = React.useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try { await onRefresh(); } finally { setRefreshing(false); }
  };

  const press = (d: string) => onPhoneChange(phone + d);
  const del = () => onPhoneChange(phone.slice(0, -1));
  const clear = () => onPhoneChange('');

  const formatPhone = (p: string) => {
    if (!p) return '';
    if (p.startsWith('+')) return p;
    if (p.length > 10) return p.replace(/(\d{3})(\d{3})(\d+)/, '$1 $2 $3');
    return p;
  };

  return (
    <SafeAreaView style={S.wrap} edges={['top', 'bottom']}>
      <ScrollView
        contentContainerStyle={S.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={Colors.primary} />}
      >
        {/* Header */}
        <View style={S.header}>
          <View style={S.headerLeft}>
            <View style={S.avatar}>
              <Text style={S.avatarTxt}>
                {(user?.fullName || user?.username || 'U').slice(0, 1).toUpperCase()}
              </Text>
            </View>
            <View>
              <Text style={S.hello}>أهلاً</Text>
              <Text style={S.name} numberOfLines={1}>
                {user?.fullName || user?.username || `#${user?.userId}`}
              </Text>
            </View>
          </View>
          <Pressable onPress={onLogout} hitSlop={12} style={S.logoutBtn}>
            <Ionicons name="log-out-outline" size={22} color={Colors.textMuted} />
          </Pressable>
        </View>

        {/* Balance card */}
        <LinearGradient
          colors={[Colors.gradStart, Colors.gradEnd]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={S.balCard}
        >
          <View style={S.balRow}>
            <View>
              <Text style={S.balLabel}>الرصيد المتاح</Text>
              <Text style={S.balAmount}>${user?.balance?.toFixed(2) ?? '0.00'}</Text>
            </View>
            <View style={S.balIcon}>
              <Ionicons name="wallet" size={28} color="#fff" />
            </View>
          </View>
          <View style={S.balDivider} />
          <View style={S.balStats}>
            <View style={S.balStat}>
              <Ionicons name="call-outline" size={14} color="rgba(255,255,255,0.85)" />
              <Text style={S.balStatTxt}>${user?.cost?.toFixed(2) ?? '0.20'} للمكالمة</Text>
            </View>
            <View style={S.balStat}>
              <Ionicons name="layers-outline" size={14} color="rgba(255,255,255,0.85)" />
              <Text style={S.balStatTxt}>{user?.possibleCalls ?? 0} متاحة</Text>
            </View>
          </View>
        </LinearGradient>

        {/* Phone display */}
        <View style={S.display}>
          <Text style={[S.phone, !phone && S.phonePlaceholder]} numberOfLines={1} adjustsFontSizeToFit>
            {phone ? formatPhone(phone) : 'أدخل الرقم'}
          </Text>
          {phone ? <DeleteKey onPress={del} onLongPress={clear} /> : null}
        </View>

        {/* Numpad */}
        <Numpad onPress={press} onDelete={del} onLongDelete={clear} />

        {/* Call button */}
        <View style={S.callBox}>
          <Pressable
            onPress={() => { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium); onCall(); }}
            disabled={!phone}
            style={({ pressed }) => [S.callBtnWrap, !phone && S.btnDisabled, pressed && S.btnPressed]}
          >
            <LinearGradient colors={['#22C55E', '#16A34A']} style={S.callBtn}>
              <Ionicons name="call" size={32} color="#fff" />
            </LinearGradient>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const S = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: Colors.bg },
  scroll: { flexGrow: 1, paddingBottom: 40 },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: Spacing.xl, paddingVertical: Spacing.lg,
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: 12, flex: 1 },
  avatar: {
    width: 44, height: 44, borderRadius: Radii.full,
    backgroundColor: Colors.primarySoft,
    borderWidth: 1.5, borderColor: Colors.primary,
    justifyContent: 'center', alignItems: 'center',
  },
  avatarTxt: { color: Colors.primary, fontSize: 18, fontWeight: '800' },
  hello: { color: Colors.textMuted, fontSize: 12 },
  name: { color: Colors.text, fontSize: 16, fontWeight: '700', maxWidth: 200 },
  logoutBtn: { padding: 8 },

  balCard: {
    marginHorizontal: Spacing.xl, marginBottom: Spacing.xl,
    borderRadius: Radii.xl, padding: Spacing.xl,
    shadowColor: Colors.primary,
    shadowOpacity: 0.35, shadowRadius: 16, shadowOffset: { width: 0, height: 6 },
    elevation: 8,
  },
  balRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  balLabel: { color: 'rgba(255,255,255,0.85)', fontSize: 13, fontWeight: '500' },
  balAmount: { color: '#fff', fontSize: 36, fontWeight: '800', marginTop: 2 },
  balIcon: {
    width: 56, height: 56, borderRadius: Radii.full,
    backgroundColor: 'rgba(255,255,255,0.15)',
    justifyContent: 'center', alignItems: 'center',
  },
  balDivider: { height: 1, backgroundColor: 'rgba(255,255,255,0.2)', marginVertical: Spacing.md },
  balStats: { flexDirection: 'row', justifyContent: 'space-between' },
  balStat: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  balStatTxt: { color: '#fff', fontSize: 12, fontWeight: '600' },

  display: {
    minHeight: 70,
    paddingHorizontal: Spacing.xl,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    marginBottom: Spacing.lg,
  },
  phone: {
    color: Colors.text, fontSize: 32, fontWeight: '300',
    letterSpacing: 1.5, flex: 1, textAlign: 'center',
  },
  phonePlaceholder: { color: Colors.textDim, fontSize: 18 },

  callBox: { alignItems: 'center', marginTop: Spacing.xl },
  callBtnWrap: { borderRadius: Radii.full, overflow: 'hidden', elevation: 8 },
  callBtn: {
    width: 78, height: 78, borderRadius: Radii.full,
    justifyContent: 'center', alignItems: 'center',
  },
  btnDisabled: { opacity: 0.4 },
  btnPressed: { transform: [{ scale: 0.92 }] },
});
