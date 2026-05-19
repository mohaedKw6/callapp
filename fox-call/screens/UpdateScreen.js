import React, { useState, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import { cacheDirectory, createDownloadResumable } from 'expo-file-system';
import { getInfoAsync, deleteAsync } from 'expo-file-system/legacy';
import * as IntentLauncher from 'expo-intent-launcher';
import { Colors } from '../theme/colors';

// ─── Constants ──────────────────────────────────────────────────────────────
const APK_FILE_NAME = 'fox-call-update.apk';
const APK_LOCAL_URI = cacheDirectory + APK_FILE_NAME;
// FileProvider authority (must match AndroidManifest.xml)
const FILE_PROVIDER_AUTHORITY = 'com.mohamedqm.foxcall.fileprovider';
const CONTENT_URI = `content://${FILE_PROVIDER_AUTHORITY}/cache/${APK_FILE_NAME}`;

export default function UpdateScreen({ downloadUrl, messageAr, latestVersion, apkSize }) {
  const [phase, setPhase] = useState('idle'); // idle | downloading | downloaded | installing | error
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState('');
  const downloadRef = useRef(null);

  const formatSize = (bytes) => {
    if (!bytes) return '';
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(1)} MB`;
  };

  const handleDownload = async () => {
    if (!downloadUrl) {
      Alert.alert('خطأ', 'رابط التحميل غير متوفر');
      return;
    }

    try {
      setPhase('downloading');
      setProgress(0);
      setErrorMsg('');

      // Delete old APK if exists
      const fileInfo = await getInfoAsync(APK_LOCAL_URI);
      if (fileInfo.exists) {
        await deleteAsync(APK_LOCAL_URI);
      }

      // Download with progress callback
      // The downloadUrl may be a /api/fresh-download-url/ endpoint that
      // does a 302 redirect to GitHub — createDownloadResumable follows redirects automatically
      const downloadResumable = createDownloadResumable(
        downloadUrl,
        APK_LOCAL_URI,
        {},
        (downloadProgress) => {
          const total = downloadProgress.totalBytesExpectedToWrite;
          const written = downloadProgress.totalBytesWritten;
          if (total > 0) {
            const pct = Math.round((written / total) * 100);
            setProgress(pct);
          }
        }
      );

      downloadRef.current = downloadResumable;
      const result = await downloadResumable.downloadAsync();

      if (result && result.uri) {
        setProgress(100);
        setPhase('downloaded');
      } else {
        throw new Error('فشل التحميل');
      }
    } catch (e) {
      console.error('[UpdateScreen] Download error:', e);
      setPhase('error');
      setErrorMsg(e?.message || 'حدث خطأ أثناء التحميل');
    }
  };

  const handleInstall = async () => {
    try {
      setPhase('installing');

      // Verify file exists
      const fileInfo = await getInfoAsync(APK_LOCAL_URI);
      if (!fileInfo.exists) {
        throw new Error('ملف التحديث غير موجود');
      }

      // Launch install intent using FileProvider content URI
      await IntentLauncher.startActivityAsync('android.intent.action.INSTALL_PACKAGE', {
        data: CONTENT_URI,
        flags: 1, // FLAG_GRANT_READ_URI_PERMISSION
        type: 'application/vnd.android.package-archive',
      });

      // After the install activity starts, user will handle install from there
      // Reset phase in case they come back without installing
      setTimeout(() => {
        setPhase('downloaded');
      }, 3000);
    } catch (e) {
      console.error('[UpdateScreen] Install error:', e);
      // Fallback: try with ACTION_VIEW
      try {
        await IntentLauncher.startActivityAsync('android.intent.action.VIEW', {
          data: CONTENT_URI,
          flags: 1,
          type: 'application/vnd.android.package-archive',
        });
      } catch (e2) {
        setPhase('error');
        setErrorMsg('لا يمكن تثبيت التحديث. حاول مرة أخرى.');
      }
    }
  };

  const handleRetry = () => {
    setPhase('idle');
    setProgress(0);
    setErrorMsg('');
  };

  // ─── Render ────────────────────────────────────────────────────────────────
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

      {/* APK Size info */}
      {apkSize > 0 && phase === 'idle' ? (
        <Text style={S.sizeInfo}>حجم التحديث: {formatSize(apkSize)}</Text>
      ) : null}

      {/* ─── Download Progress ──────────────────────────────────────────── */}
      {phase === 'downloading' && (
        <View style={S.progressSection}>
          <View style={S.progressBg}>
            <View style={[S.progressFill, { width: `${progress}%` }]} />
          </View>
          <Text style={S.progressText}>جاري التحميل... {progress}%</Text>
        </View>
      )}

      {/* ─── Downloaded state ───────────────────────────────────────────── */}
      {phase === 'downloaded' && (
        <View style={S.downloadedSection}>
          <Text style={S.downloadedIcon}>✅</Text>
          <Text style={S.downloadedText}>تم التحميل بنجاح!</Text>
        </View>
      )}

      {/* ─── Installing state ───────────────────────────────────────────── */}
      {phase === 'installing' && (
        <View style={S.downloadedSection}>
          <Text style={S.downloadedIcon}>⚙️</Text>
          <Text style={S.downloadedText}>جاري التثبيت...</Text>
        </View>
      )}

      {/* ─── Error state ────────────────────────────────────────────────── */}
      {phase === 'error' && (
        <View style={S.errorBox}>
          <Text style={S.errorIcon}>❌</Text>
          <Text style={S.errorText}>{errorMsg}</Text>
        </View>
      )}

      {/* ─── Buttons ────────────────────────────────────────────────────── */}
      {(phase === 'idle' || phase === 'error') && (
        <TouchableOpacity style={S.downloadBtn} onPress={phase === 'error' ? handleRetry : handleDownload} activeOpacity={0.7}>
          <Text style={S.downloadBtnIcon}>⬇️</Text>
          <Text style={S.downloadBtnText}>
            {phase === 'error' ? 'إعادة المحاولة' : 'تحميل النسخة الجديدة'}
          </Text>
        </TouchableOpacity>
      )}

      {phase === 'downloading' && (
        <TouchableOpacity style={S.cancelBtn} onPress={() => {
          downloadRef.current?.cancelAsync?.();
          setPhase('idle');
          setProgress(0);
        }} activeOpacity={0.7}>
          <Text style={S.cancelBtnText}>إلغاء</Text>
        </TouchableOpacity>
      )}

      {phase === 'downloaded' && (
        <TouchableOpacity style={S.installBtn} onPress={handleInstall} activeOpacity={0.7}>
          <Text style={S.installBtnIcon}>🔄</Text>
          <Text style={S.installBtnText}>تثبيت التحديث</Text>
        </TouchableOpacity>
      )}

      {/* Info box */}
      {phase === 'idle' && (
        <View style={S.infoBox}>
          <Text style={S.infoIcon}>ℹ️</Text>
          <Text style={S.infoText}>
            النسخة الحالية لم تعد مدعومة. اضغط على زر التحميل لتنزيل النسخة الجديدة، ثم اضغط "تثبيت التحديث" لتحديث التطبيق.
          </Text>
        </View>
      )}

      {phase === 'downloaded' && (
        <View style={S.infoBox}>
          <Text style={S.infoIcon}>ℹ️</Text>
          <Text style={S.infoText}>
            اضغط على "تثبيت التحديث" واسمح بالتثبيت من المصدر عند ظهور الإعداد.
          </Text>
        </View>
      )}

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
  iconEmoji: { fontSize: 40 },
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
  versionBadgeText: { color: '#fff', fontSize: 13, fontWeight: 'bold' },
  message: {
    fontSize: 16,
    color: Colors.textMuted,
    textAlign: 'center',
    lineHeight: 26,
    marginBottom: 12,
  },
  sizeInfo: {
    fontSize: 13,
    color: Colors.textMuted,
    marginBottom: 20,
    opacity: 0.8,
  },
  // Progress
  progressSection: {
    width: '100%',
    alignItems: 'center',
    marginBottom: 20,
  },
  progressBg: {
    width: '100%',
    height: 12,
    backgroundColor: Colors.card,
    borderRadius: 6,
    overflow: 'hidden',
    marginBottom: 8,
  },
  progressFill: {
    height: '100%',
    backgroundColor: Colors.primary,
    borderRadius: 6,
  },
  progressText: {
    color: Colors.textMuted,
    fontSize: 14,
  },
  // Downloaded
  downloadedSection: {
    alignItems: 'center',
    marginBottom: 16,
  },
  downloadedIcon: { fontSize: 32, marginBottom: 4 },
  downloadedText: {
    color: '#4CAF50',
    fontSize: 16,
    fontWeight: 'bold',
  },
  // Error
  errorBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#3a1a1a',
    borderRadius: 10,
    padding: 12,
    width: '100%',
    marginBottom: 16,
    borderLeftWidth: 3,
    borderLeftColor: '#e74c3c',
  },
  errorIcon: { fontSize: 18, marginRight: 10 },
  errorText: {
    flex: 1,
    color: '#e74c3c',
    fontSize: 13,
  },
  // Info
  infoBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: Colors.card,
    borderRadius: 12,
    padding: 14,
    width: '100%',
    marginTop: 16,
    borderLeftWidth: 3,
    borderLeftColor: Colors.primary,
  },
  infoIcon: { fontSize: 18, marginRight: 10, marginTop: 1 },
  infoText: {
    flex: 1,
    fontSize: 13,
    color: Colors.textMuted,
    lineHeight: 20,
  },
  // Buttons
  downloadBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.primary,
    paddingVertical: 16,
    paddingHorizontal: 32,
    borderRadius: 14,
    width: '100%',
    marginBottom: 8,
    elevation: 4,
    shadowColor: Colors.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  downloadBtnIcon: { fontSize: 20, marginRight: 10 },
  downloadBtnText: { color: '#fff', fontSize: 18, fontWeight: 'bold' },
  installBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#4CAF50',
    paddingVertical: 16,
    paddingHorizontal: 32,
    borderRadius: 14,
    width: '100%',
    marginBottom: 8,
    elevation: 4,
    shadowColor: '#4CAF50',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
  },
  installBtnIcon: { fontSize: 20, marginRight: 10 },
  installBtnText: { color: '#fff', fontSize: 18, fontWeight: 'bold' },
  cancelBtn: {
    paddingVertical: 10,
    paddingHorizontal: 24,
  },
  cancelBtnText: {
    color: Colors.textMuted,
    fontSize: 14,
  },
});
