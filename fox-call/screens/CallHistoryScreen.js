import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, Pressable, FlatList, StyleSheet, ActivityIndicator, RefreshControl } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as Haptics from 'expo-haptics';
import { Colors, Radii, Spacing } from '../theme/colors';
import { t } from '../i18n';

const STATUS_MAP = {
  completed: { label: 'مكتملة', color: Colors.success, icon: 'checkmark-circle' },
  failed: { label: 'فشلت', color: Colors.danger, icon: 'close-circle' },
  missed: { label: 'فائتة', color: Colors.warning, icon: 'alert-circle' },
  ended: { label: 'انتهت', color: Colors.textMuted, icon: 'stop-circle' },
};

const getStatusInfo = (status) => STATUS_MAP[status] || { label: status || '—', color: Colors.textDim, icon: 'help-circle-outline' };

const fmtDuration = (s) => {
  if (!s || s <= 0) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
};

const fmtDate = (d) => {
  if (!d) return '—';
  try {
    const date = new Date(d);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    const timeStr = date.toLocaleTimeString('ar', { hour: '2-digit', minute: '2-digit' });

    if (diffDays === 0) return `${t('back') === 'Back' ? 'Today' : 'اليوم'} ${timeStr}`;
    if (diffDays === 1) return `${t('back') === 'Back' ? 'Yesterday' : 'أمس'} ${timeStr}`;
    if (diffDays < 7) return `${diffDays} ${t('back') === 'Back' ? 'days ago' : 'أيام'}`;
    return date.toLocaleDateString('ar', { month: 'short', day: 'numeric' }) + ' ' + timeStr;
  } catch {
    return d;
  }
};

export default function CallHistoryScreen({ api, onBack }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const fetchHistory = useCallback(async () => {
    try {
      setError(null);
      const data = await api.getCallHistory();
      setHistory(data?.calls || data || []);
    } catch (e) {
      setError(e?.message || t('failed'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [api]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const onRefresh = () => {
    setRefreshing(true);
    Haptics.selectionAsync();
    fetchHistory();
  };

  const renderItem = ({ item }) => {
    const statusInfo = getStatusInfo(item.status);
    return (
      <View style={S.item}>
        <View style={[S.statusDot, { backgroundColor: statusInfo.color }]} />
        <View style={S.itemContent}>
          <View style={S.itemTop}>
            <Text style={S.itemPhone} numberOfLines={1}>{item.to || item.phone || '—'}</Text>
            <Text style={S.itemTime}>{fmtDate(item.created_at || item.date || item.timestamp)}</Text>
          </View>
          <View style={S.itemBottom}>
            <Ionicons name={statusInfo.icon} size={14} color={statusInfo.color} />
            <Text style={[S.itemStatus, { color: statusInfo.color }]}>{statusInfo.label}</Text>
            <Text style={S.itemDuration}>{fmtDuration(item.duration)}</Text>
          </View>
        </View>
      </View>
    );
  };

  const renderEmpty = () => (
    <View style={S.emptyWrap}>
      <Ionicons name="time-outline" size={64} color={Colors.textDim} />
      <Text style={S.emptyTitle}>{t('noCalls')}</Text>
    </View>
  );

  return (
    <SafeAreaView style={S.wrap} edges={['top', 'bottom']}>
      {/* Header */}
      <View style={S.header}>
        <Pressable onPress={() => { Haptics.selectionAsync(); onBack(); }} hitSlop={12} style={S.backBtn}>
          <Ionicons name="arrow-back" size={24} color={Colors.text} />
        </Pressable>
        <Text style={S.headerTitle}>{t('callHistoryTitle')}</Text>
        <View style={{ width: 40 }} />
      </View>

      {/* Content */}
      {loading ? (
        <View style={S.centerWrap}>
          <ActivityIndicator size="large" color={Colors.primary} />
          <Text style={S.loadingTxt}>{t('loading')}</Text>
        </View>
      ) : error ? (
        <View style={S.centerWrap}>
          <Ionicons name="alert-circle-outline" size={48} color={Colors.danger} />
          <Text style={S.errorText}>{error}</Text>
          <Pressable onPress={fetchHistory} style={S.retryBtn}>
            <Text style={S.retryTxt}>{t('refresh')}</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={history}
          keyExtractor={(item, i) => item.id?.toString() || item.call_id?.toString() || i.toString()}
          renderItem={renderItem}
          ListEmptyComponent={renderEmpty}
          contentContainerStyle={history.length === 0 ? S.flatListEmpty : S.flatList}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.primary} />}
        />
      )}
    </SafeAreaView>
  );
}

const S = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: Colors.bg },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: Spacing.lg, paddingVertical: Spacing.md,
    borderBottomWidth: 1, borderBottomColor: Colors.border,
  },
  backBtn: { padding: 8 },
  headerTitle: { color: Colors.text, fontSize: 18, fontWeight: '700' },

  centerWrap: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: Spacing.xl, gap: 12 },
  loadingTxt: { color: Colors.textMuted, fontSize: 14, marginTop: Spacing.sm },
  errorText: { color: Colors.danger, fontSize: 14, textAlign: 'center' },
  retryBtn: {
    marginTop: Spacing.md, paddingHorizontal: Spacing.xl, paddingVertical: Spacing.md,
    backgroundColor: Colors.primarySoft, borderRadius: Radii.lg,
  },
  retryTxt: { color: Colors.primary, fontSize: 14, fontWeight: '600' },

  flatList: { paddingHorizontal: Spacing.lg, paddingTop: Spacing.md, paddingBottom: Spacing.xxl },
  flatListEmpty: { flexGrow: 1 },

  item: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: Colors.card, borderRadius: Radii.lg,
    padding: Spacing.lg, marginBottom: Spacing.sm,
    borderWidth: 1, borderColor: Colors.borderSoft,
  },
  statusDot: { width: 10, height: 10, borderRadius: 5, marginLeft: Spacing.md },
  itemContent: { flex: 1, marginRight: Spacing.md },
  itemTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  itemPhone: { color: Colors.text, fontSize: 15, fontWeight: '600', flex: 1, letterSpacing: 0.5 },
  itemTime: { color: Colors.textDim, fontSize: 11, marginLeft: Spacing.sm },
  itemBottom: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  itemStatus: { fontSize: 12, fontWeight: '600' },
  itemDuration: { color: Colors.textMuted, fontSize: 12, marginLeft: Spacing.sm },

  emptyWrap: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: 8 },
  emptyTitle: { color: Colors.textMuted, fontSize: 18, fontWeight: '600', marginTop: Spacing.lg },
});
