import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import Colors from '../theme/colors';
import farmApi from '../services/serverApi';

export default function LoginScreen({ onLogin }) {
  const [key, setKey] = useState('');
  const [server, setServer] = useState('https://eaiupvh6.up.railway.app');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async () => {
    if (!key.trim()) {
      setError('اكتب مفتاح الفارم');
      return;
    }
    setLoading(true);
    setError('');
    try {
      farmApi.setServer(server.trim());
      const res = await farmApi.authenticate(key.trim());
      if (res.ok && res.token) {
        onLogin(res.token, server.trim());
      } else {
        setError('مفتاح غلط');
      }
    } catch (e) {
      setError(e.message || 'فشل الاتصال');
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <StatusBar style="light" />
      <View style={styles.inner}>
        {/* Logo */}
        <View style={styles.logoContainer}>
          <Text style={styles.logoEmoji}>🦊</Text>
          <Text style={styles.logoText}>Fox Farm</Text>
          <Text style={styles.logoSub}>إنشاء حسابات Telicall</Text>
        </View>

        {/* Server URL */}
        <View style={styles.field}>
          <Text style={styles.label}>رابط السيرفر</Text>
          <TextInput
            style={styles.input}
            value={server}
            onChangeText={setServer}
            placeholder="https://..."
            placeholderTextColor={Colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />
        </View>

        {/* Farm Key */}
        <View style={styles.field}>
          <Text style={styles.label}>مفتاح الفارم</Text>
          <TextInput
            style={styles.input}
            value={key}
            onChangeText={setKey}
            placeholder="أدخل المفتاح"
            placeholderTextColor={Colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
          />
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        {/* Login Button */}
        <TouchableOpacity
          style={[styles.btn, loading && styles.btnDisabled]}
          onPress={handleLogin}
          disabled={loading}
        >
          <Text style={styles.btnText}>
            {loading ? 'جاري الاتصال...' : 'دخول'}
          </Text>
        </TouchableOpacity>

        <Text style={styles.hint}>
          المفتاح بيتم الحصول عليه من الأدمن
        </Text>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.bg },
  inner: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  logoContainer: { alignItems: 'center', marginBottom: 48 },
  logoEmoji: { fontSize: 72, marginBottom: 8 },
  logoText: {
    fontSize: 36,
    fontWeight: 'bold',
    color: Colors.primary,
    letterSpacing: 1,
  },
  logoSub: { fontSize: 16, color: Colors.textSecondary, marginTop: 4 },
  field: { marginBottom: 20 },
  label: {
    fontSize: 14,
    color: Colors.textSecondary,
    marginBottom: 6,
    fontWeight: '600',
  },
  input: {
    backgroundColor: Colors.bgInput,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 12,
    padding: 14,
    fontSize: 16,
    color: Colors.text,
  },
  btn: {
    backgroundColor: Colors.primary,
    borderRadius: 14,
    padding: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  btnDisabled: { opacity: 0.5 },
  btnText: { fontSize: 18, fontWeight: 'bold', color: '#fff' },
  error: {
    color: Colors.danger,
    textAlign: 'center',
    marginBottom: 8,
    fontSize: 14,
  },
  hint: {
    color: Colors.textMuted,
    textAlign: 'center',
    marginTop: 16,
    fontSize: 13,
  },
});
