import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking, Image } from 'react-native';
import { Colors } from '../theme/colors';

export default function UpdateScreen({ downloadUrl, messageAr, latestVersion }) {
  const handleDownload = () => {
    if (downloadUrl) {
      Linking.openURL(downloadUrl).catch(() => {
        // Fallback: try opening in browser
        Linking.openURL('https://github.com/MohamedQM/callapp').catch(() => {});
      });
    }
  };

  return (
    <View style={S.container}>
      {/* Decorative top circle */}
      <View style={S.topCircle} />

      {/* Icon */}
      <View style={S.iconWrap}>
        <Text style={S.iconEmoji}>🦊</Text>
      </View>

      {/* Title */}
      <Text style={S.title}>تحديث مطلوب</Text>

      {/* Version badge */}
      {latestVersion ? (
        <View style={S.versionBadge}>
          <Text style={S.versionBadgeText}>v{latestVersion}</Text>
        </View>
      ) : null}

      {/* Message */}
      <Text style={S.message}>
        {messageAr || 'يتوفر تحديث جديد للتطبيق! يرجى تحميل النسخة الجديدة للمتابعة.'}
      </Text>

      {/* Info box */}
      <View style={S.infoBox}>
        <Text style={S.infoIcon}>ℹ️</Text>
        <Text style={S.infoText}>
          النسخة الحالية لم تعد مدعومة. يجب تحديث التطبيق للاستمرار في استخدام الخدمة.
        </Text>
      </View>

      {/* Download button */}
      <TouchableOpacity style={S.downloadBtn} onPress={handleDownload} activeOpacity={0.7}>
        <Text style={S.downloadBtnIcon}>⬇️</Text>
        <Text style={S.downloadBtnText}>تحميل النسخة الجديدة</Text>
      </TouchableOpacity>

      {/* Subtitle hint */}
      <Text style={S.hint}>
        بعد التحميل، قم بتثبيت النسخة الجديدة ثم افتح التطبيق مجدداً
      </Text>

      {/* Bottom decorative */}
      <View style={S.bottomCircle} />
    </View>
  );
}

const S = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
    position: 'relative',
    overflow: 'hidden',
  },
  topCircle: {
    position: 'absolute',
    top: -120,
    right: -80,
    width: 250,
    height: 250,
    borderRadius: 125,
    backgroundColor: Colors.primary + '15',
  },
  bottomCircle: {
    position: 'absolute',
    bottom: -80,
    left: -60,
    width: 200,
    height: 200,
    borderRadius: 100,
    backgroundColor: Colors.primary + '10',
  },
  iconWrap: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: Colors.primary + '20',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  iconEmoji: {
    fontSize: 40,
  },
  title: {
    fontSize: 26,
    fontWeight: 'bold',
    color: Colors.text,
    marginBottom: 8,
    textAlign: 'center',
  },
  versionBadge: {
    backgroundColor: Colors.primary,
    paddingHorizontal: 14,
    paddingVertical: 4,
    borderRadius: 12,
    marginBottom: 16,
  },
  versionBadgeText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: 'bold',
  },
  message: {
    fontSize: 16,
    color: Colors.textMuted,
    textAlign: 'center',
    lineHeight: 26,
    marginBottom: 20,
  },
  infoBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: Colors.card,
    borderRadius: 12,
    padding: 14,
    width: '100%',
    marginBottom: 28,
    borderLeftWidth: 3,
    borderLeftColor: Colors.primary,
  },
  infoIcon: {
    fontSize: 18,
    marginRight: 10,
    marginTop: 1,
  },
  infoText: {
    flex: 1,
    fontSize: 13,
    color: Colors.textMuted,
    lineHeight: 20,
  },
  downloadBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.primary,
    paddingVertical: 16,
    paddingHorizontal: 32,
    borderRadius: 14,
    width: '100%',
    marginBottom: 16,
    elevation: 4,
    shadowColor: Colors.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  downloadBtnIcon: {
    fontSize: 20,
    marginRight: 10,
  },
  downloadBtnText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  hint: {
    fontSize: 12,
    color: Colors.textMuted,
    textAlign: 'center',
    opacity: 0.7,
  },
});
