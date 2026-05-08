import React, { useState, useRef, useCallback } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Alert,
  Vibration,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import Colors from '../theme/colors';
import farmApi from '../services/serverApi';
import {
  createOneAccount,
  createMultipleAccounts,
} from '../services/accountCreator';

export default function FarmScreen({ onLogout }) {
  const [count, setCount] = useState('5');
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState('جاهز للبدء');
  const [log, setLog] = useState([]);
  const [stats, setStats] = useState({
    created: 0,
    failed: 0,
    uploaded: 0,
  });
  const [ipBlocked, setIpBlocked] = useState(false);
  const [currentBatch, setCurrentBatch] = useState([]);

  const stopRef = useRef(false);

  const addLog = useCallback((msg, type = 'info') => {
    const time = new Date().toLocaleTimeString('ar-EG');
    setLog((prev) => [...prev.slice(-100), { time, msg, type }]);
  }, []);

  const handleStop = () => {
    stopRef.current = true;
    setStatus('جاري الإيقاف...');
  };

  const uploadBatch = async (accounts) => {
    if (accounts.length === 0) return 0;
    try {
      addLog(`📤 رفع ${accounts.length} حساب على السيرفر...`, 'info');
      const res = await farmApi.uploadAccounts(accounts);
      const added = res.added || 0;
      setStats((s) => ({ ...s, uploaded: s.uploaded + added }));
      addLog(`✅ تم رفع ${added} حساب`, 'success');
      return added;
    } catch (e) {
      addLog(`❌ فشل الرفع: ${e.message}`, 'error');
      return 0;
    }
  };

  const handleStart = async () => {
    const num = parseInt(count) || 5;
    if (num < 1 || num > 100) {
      Alert.alert('خطأ', 'عدد الحسابات لازم يكون بين 1 و 100');
      return;
    }

    stopRef.current = false;
    setRunning(true);
    setIpBlocked(false);
    setStats({ created: 0, failed: 0, uploaded: 0 });
    setCurrentBatch([]);
    addLog(`🚀 بدء إنشاء ${num} حساب...`, 'info');

    let totalCreated = 0;
    let totalFailed = 0;
    let batchAccounts = [];

    for (let i = 0; i < num; i++) {
      if (stopRef.current) {
        addLog('⏹️ تم الإيقاف', 'warning');
        break;
      }

      setStatus(`حساب ${i + 1} من ${num}...`);

      const result = await createOneAccount((msg) => {
        setStatus(`[${i + 1}/${num}] ${msg}`);
      });

      if (result.success) {
        totalCreated++;
        batchAccounts.push(result.account);
        setCurrentBatch([...batchAccounts]);
        setStats((s) => ({ ...s, created: s.created + 1 }));
        addLog(`✅ حساب جديد: ${result.account.email}`, 'success');

        // Upload every 3 accounts or on the last one
        if (batchAccounts.length >= 3 || i === num - 1) {
          await uploadBatch([...batchAccounts]);
          batchAccounts = [];
          setCurrentBatch([]);
        }
      } else if (result.error === 'IP_BLOCKED') {
        setIpBlocked(true);
        Vibration.vibrate([0, 300, 100, 300]);
        addLog('🚫 الآي بي بتاعك اتحظر!', 'error');
        addLog('🔄 افتح VPN وحاول تاني', 'warning');

        // Upload what we have so far
        if (batchAccounts.length > 0) {
          await uploadBatch([...batchAccounts]);
          batchAccounts = [];
          setCurrentBatch([]);
        }
        break;
      } else {
        totalFailed++;
        setStats((s) => ({ ...s, failed: s.failed + 1 }));
        addLog(`❌ فشل: ${result.error}`, 'error');
      }

      // Delay between accounts
      if (i < num - 1 && !stopRef.current) {
        const delay = Math.floor(Math.random() * 3000) + 2000;
        setStatus(`انتظار ${Math.round(delay / 1000)} ثانية...`);
        await new Promise((r) => setTimeout(r, delay));
      }
    }

    // Upload any remaining accounts
    if (batchAccounts.length > 0) {
      await uploadBatch([...batchAccounts]);
    }

    setStats((s) => ({ ...s, created: totalCreated, failed: totalFailed }));
    setStatus(
      stopRef.current
        ? 'تم الإيقاف'
        : totalCreated > 0
        ? `تم إنشاء ${totalCreated} حساب ✅`
        : 'لم يتم إنشاء أي حساب'
    );
    setRunning(false);
  };

  const refreshStats = async () => {
    try {
      const res = await farmApi.getStats();
      setStats((s) => ({
        ...s,
        serverTokens: res.ready_tokens || 0,
        serverUsed: res.used_accounts || 0,
        serverAccounts: res.accounts_in_file || 0,
      }));
    } catch (e) {
      addLog('فشل تحميل الإحصائيات', 'error');
    }
  };

  return (
    <View style={styles.container}>
      <StatusBar style="light" />

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>🦊 Fox Farm</Text>
        <TouchableOpacity onPress={onLogout} style={styles.logoutBtn}>
          <Text style={styles.logoutText}>خروج</Text>
        </TouchableOpacity>
      </View>

      {/* IP Blocked Warning */}
      {ipBlocked && (
        <View style={styles.blockedBanner}>
          <Text style={styles.blockedEmoji}>🚫</Text>
          <View style={styles.blockedText}>
            <Text style={styles.blockedTitle}>الآي بي اتحظر!</Text>
            <Text style={styles.blockedSub}>
              افتح VPN وحاول تاني
            </Text>
          </View>
          <TouchableOpacity
            style={styles.vpnBtn}
            onPress={() => {
              setIpBlocked(false);
              addLog('🔄 تم إعادة التعيين - افتح VPN وابدأ من جديد', 'info');
            }}
          >
            <Text style={styles.vpnBtnText}>فهمت</Text>
          </TouchableOpacity>
        </View>
      )}

      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
      >
        {/* Stats Cards */}
        <View style={styles.statsRow}>
          <View style={[styles.statCard, { borderLeftColor: Colors.success }]}>
            <Text style={styles.statNumber}>{stats.created}</Text>
            <Text style={styles.statLabel}>تم إنشاؤها</Text>
          </View>
          <View style={[styles.statCard, { borderLeftColor: Colors.danger }]}>
            <Text style={styles.statNumber}>{stats.failed}</Text>
            <Text style={styles.statLabel}>فشلت</Text>
          </View>
          <View style={[styles.statCard, { borderLeftColor: Colors.primary }]}>
            <Text style={styles.statNumber}>{stats.uploaded}</Text>
            <Text style={styles.statLabel}>تم رفعها</Text>
          </View>
        </View>

        {/* Current Batch */}
        {currentBatch.length > 0 && (
          <View style={styles.batchCard}>
            <Text style={styles.batchTitle}>
              📦 دفعة حالية ({currentBatch.length})
            </Text>
            {currentBatch.map((acc, i) => (
              <Text key={i} style={styles.batchItem}>
                {acc.email}
              </Text>
            ))}
          </View>
        )}

        {/* Controls */}
        <View style={styles.controlsCard}>
          <Text style={styles.cardTitle}>عدد الحسابات</Text>
          <TextInput
            style={styles.countInput}
            value={count}
            onChangeText={setCount}
            keyboardType="number-pad"
            editable={!running}
            maxLength={3}
          />
          <View style={styles.quickBtns}>
            {[5, 10, 20, 50].map((n) => (
              <TouchableOpacity
                key={n}
                style={[styles.quickBtn, count === String(n) && styles.quickBtnActive]}
                onPress={() => setCount(String(n))}
                disabled={running}
              >
                <Text
                  style={[
                    styles.quickBtnText,
                    count === String(n) && styles.quickBtnTextActive,
                  ]}
                >
                  {n}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <View style={styles.actionBtns}>
            {!running ? (
              <TouchableOpacity style={styles.startBtn} onPress={handleStart}>
                <Text style={styles.startBtnText}>🚀 ابدأ الإنشاء</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity style={styles.stopBtn} onPress={handleStop}>
                <Text style={styles.stopBtnText}>⏹️ إيقاف</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>

        {/* Status */}
        <View style={styles.statusCard}>
          <Text style={styles.statusText}>{status}</Text>
        </View>

        {/* Log */}
        <View style={styles.logCard}>
          <View style={styles.logHeader}>
            <Text style={styles.logTitle}>السجل</Text>
            <TouchableOpacity onPress={() => setLog([])}>
              <Text style={styles.logClear}>مسح</Text>
            </TouchableOpacity>
          </View>
          {log.slice(-20).map((entry, i) => (
            <View key={i} style={styles.logRow}>
              <Text style={styles.logTime}>{entry.time}</Text>
              <Text
                style={[
                  styles.logMsg,
                  entry.type === 'success' && styles.logSuccess,
                  entry.type === 'error' && styles.logError,
                  entry.type === 'warning' && styles.logWarning,
                ]}
              >
                {entry.msg}
              </Text>
            </View>
          ))}
          {log.length === 0 && (
            <Text style={styles.logEmpty}>لا يوجد سجلات بعد</Text>
          )}
        </View>

        {/* Server Stats */}
        <TouchableOpacity style={styles.refreshBtn} onPress={refreshStats}>
          <Text style={styles.refreshBtnText}>🔄 تحديث إحصائيات السيرفر</Text>
        </TouchableOpacity>
        {stats.serverTokens !== undefined && (
          <View style={styles.serverStatsCard}>
            <Text style={styles.serverStatsTitle}>إحصائيات السيرفر</Text>
            <View style={styles.serverStatsRow}>
              <Text style={styles.serverStatsLabel}>توكنات جاهزة:</Text>
              <Text style={styles.serverStatsValue}>{stats.serverTokens}</Text>
            </View>
            <View style={styles.serverStatsRow}>
              <Text style={styles.serverStatsLabel}>حسابات مستعملة:</Text>
              <Text style={styles.serverStatsValue}>{stats.serverUsed}</Text>
            </View>
            <View style={styles.serverStatsRow}>
              <Text style={styles.serverStatsLabel}>حسابات في الملف:</Text>
              <Text style={styles.serverStatsValue}>{stats.serverAccounts}</Text>
            </View>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.bg },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 14,
    backgroundColor: Colors.bgCard,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  headerTitle: { fontSize: 22, fontWeight: 'bold', color: Colors.primary },
  logoutBtn: { padding: 8 },
  logoutText: { color: Colors.textSecondary, fontSize: 14 },
  blockedBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.dangerBg,
    borderWidth: 1,
    borderColor: Colors.danger,
    borderRadius: 12,
    padding: 14,
    marginHorizontal: 16,
    marginTop: 12,
  },
  blockedEmoji: { fontSize: 28, marginRight: 10 },
  blockedText: { flex: 1 },
  blockedTitle: { color: Colors.danger, fontWeight: 'bold', fontSize: 16 },
  blockedSub: { color: Colors.textSecondary, fontSize: 13, marginTop: 2 },
  vpnBtn: {
    backgroundColor: Colors.danger,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  vpnBtnText: { color: '#fff', fontWeight: 'bold', fontSize: 14 },
  scrollView: { flex: 1 },
  scrollContent: { padding: 16, paddingBottom: 40 },
  statsRow: { flexDirection: 'row', gap: 10, marginBottom: 16 },
  statCard: {
    flex: 1,
    backgroundColor: Colors.bgCard,
    borderRadius: 12,
    padding: 14,
    borderLeftWidth: 3,
  },
  statNumber: {
    fontSize: 28,
    fontWeight: 'bold',
    color: Colors.text,
    textAlign: 'center',
  },
  statLabel: {
    fontSize: 12,
    color: Colors.textSecondary,
    textAlign: 'center',
    marginTop: 4,
  },
  batchCard: {
    backgroundColor: Colors.bgCard,
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: Colors.primary,
  },
  batchTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: Colors.primary,
    marginBottom: 6,
  },
  batchItem: { fontSize: 12, color: Colors.textSecondary, marginVertical: 1 },
  controlsCard: {
    backgroundColor: Colors.bgCard,
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: Colors.text,
    marginBottom: 10,
  },
  countInput: {
    backgroundColor: Colors.bgInput,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 10,
    padding: 12,
    fontSize: 24,
    color: Colors.text,
    textAlign: 'center',
    fontWeight: 'bold',
  },
  quickBtns: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
    marginTop: 10,
  },
  quickBtn: {
    backgroundColor: Colors.bgInput,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  quickBtnActive: {
    borderColor: Colors.primary,
    backgroundColor: Colors.primaryGlow,
  },
  quickBtnText: { color: Colors.textSecondary, fontSize: 14, fontWeight: '600' },
  quickBtnTextActive: { color: Colors.primary },
  actionBtns: { marginTop: 16 },
  startBtn: {
    backgroundColor: Colors.primary,
    borderRadius: 14,
    padding: 16,
    alignItems: 'center',
  },
  startBtnText: { color: '#fff', fontSize: 18, fontWeight: 'bold' },
  stopBtn: {
    backgroundColor: Colors.danger,
    borderRadius: 14,
    padding: 16,
    alignItems: 'center',
  },
  stopBtnText: { color: '#fff', fontSize: 18, fontWeight: 'bold' },
  statusCard: {
    backgroundColor: Colors.bgCard,
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  statusText: {
    fontSize: 15,
    color: Colors.text,
    textAlign: 'center',
  },
  logCard: {
    backgroundColor: Colors.bgCard,
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
  },
  logHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  logTitle: { fontSize: 14, fontWeight: 'bold', color: Colors.text },
  logClear: { fontSize: 12, color: Colors.textMuted },
  logRow: { flexDirection: 'row', marginVertical: 2 },
  logTime: { fontSize: 10, color: Colors.textMuted, width: 70 },
  logMsg: { fontSize: 12, color: Colors.textSecondary, flex: 1 },
  logSuccess: { color: Colors.success },
  logError: { color: Colors.danger },
  logWarning: { color: Colors.warning },
  logEmpty: {
    fontSize: 13,
    color: Colors.textMuted,
    textAlign: 'center',
    paddingVertical: 10,
  },
  refreshBtn: {
    backgroundColor: Colors.bgCard,
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
    marginBottom: 12,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  refreshBtnText: { color: Colors.textSecondary, fontSize: 14 },
  serverStatsCard: {
    backgroundColor: Colors.bgCard,
    borderRadius: 12,
    padding: 16,
  },
  serverStatsTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: Colors.text,
    marginBottom: 8,
  },
  serverStatsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginVertical: 3,
  },
  serverStatsLabel: { fontSize: 13, color: Colors.textSecondary },
  serverStatsValue: { fontSize: 13, color: Colors.text, fontWeight: '600' },
});
