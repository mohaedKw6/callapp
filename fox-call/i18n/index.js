import { getItemAsync, setItemAsync } from 'expo-secure-store';

const LANG_KEY = 'foxcall_lang_v1';

const translations = {
  ar: {
    // App
    loading: 'جاري التحميل...',
    // DialerScreen
    balance: 'رصيدك',
    calls: 'مكالمة متاحة',
    callCost: 'سعر المكالمة',
    call: 'اتصال',
    callHistory: 'سجل المكالمات',
    logout: 'خروج',
    refresh: 'تحديث',
    insufficientBalance: 'رصيد غير كافي',
    insufficientMsg: 'رصيدك {balance}$ مش كافي للمكالمة. الحد الأدنى {cost}$',
    micPermission: 'صلاحية الميكروفون',
    micMsg: 'يحتاج التطبيق الميكروفون لإجراء المكالمات الصوتية',
    allow: 'سماح',
    deny: 'رفض',
    alert: 'تنبيه',
    micRequired: 'لازم تسمح للميكروفون عشان تعمل مكالمة',
    failed: 'فشل',
    tokenChanged: 'تم تغيير التوكن برجاء ادخال التوكن الجديد',
    confirm: 'تأكيد',
    wantLogout: 'تريد تسجيل الخروج؟',
    cancel: 'إلغاء',
    exit: 'خروج',
    enterToken: 'أدخل التوكن',
    connect: 'اتصال',
    // CallScreen
    connecting: 'جاري الاتصال...',
    ringing: 'جاري الرنين...',
    connected: 'متصل الآن',
    connectedRecording: 'متصل ● تسجيل',
    callEnded: 'انتهت المكالمة',
    callFailed: 'فشلت المكالمة',
    from: 'من',
    maxDuration: 'الحد الأقصى',
    recording: 'تسجيل',
    stop: 'إيقاف',
    muted: 'مكتوم',
    mic: 'مايك',
    earpiece: 'أذن',
    speaker: 'سماعة',
    bluetooth: 'بلوتوث',
    keypad: 'أرقام',
    // CallHistoryScreen
    callHistoryTitle: 'سجل المكالمات',
    noCalls: 'لا توجد مكالمات',
    back: 'رجوع',
    // UpdateScreen
    updateAvailable: 'تحديث متاح',
    newVersion: 'إصدار جديد',
    download: 'تحميل',
    downloading: 'جاري التحميل...',
    installing: 'جاري التثبيت...',
    later: 'لاحقاً',
    // TokenScreen
    tokenPlaceholder: 'أدخل توكن Fox Call',
    tokenHint: 'احصل على التوكن من بوت التليجرام',
  },
  en: {
    // App
    loading: 'Loading...',
    // DialerScreen
    balance: 'Balance',
    calls: 'calls available',
    callCost: 'Call cost',
    call: 'Call',
    callHistory: 'Call History',
    logout: 'Logout',
    refresh: 'Refresh',
    insufficientBalance: 'Insufficient Balance',
    insufficientMsg: 'Your balance {balance}$ is not enough. Minimum {cost}$',
    micPermission: 'Microphone Permission',
    micMsg: 'The app needs microphone access for voice calls',
    allow: 'Allow',
    deny: 'Deny',
    alert: 'Alert',
    micRequired: 'Microphone permission is required for calls',
    failed: 'Failed',
    tokenChanged: 'Token has changed, please enter the new token',
    confirm: 'Confirm',
    wantLogout: 'Do you want to logout?',
    cancel: 'Cancel',
    exit: 'Exit',
    enterToken: 'Enter Token',
    connect: 'Connect',
    // CallScreen
    connecting: 'Connecting...',
    ringing: 'Ringing...',
    connected: 'Connected',
    connectedRecording: 'Connected ● Recording',
    callEnded: 'Call Ended',
    callFailed: 'Call Failed',
    from: 'From',
    maxDuration: 'Max Duration',
    recording: 'Recording',
    stop: 'Stop',
    muted: 'Muted',
    mic: 'Mic',
    earpiece: 'Earpiece',
    speaker: 'Speaker',
    bluetooth: 'Bluetooth',
    keypad: 'Keypad',
    // CallHistoryScreen
    callHistoryTitle: 'Call History',
    noCalls: 'No calls yet',
    back: 'Back',
    // UpdateScreen
    updateAvailable: 'Update Available',
    newVersion: 'New Version',
    download: 'Download',
    downloading: 'Downloading...',
    installing: 'Installing...',
    later: 'Later',
    // TokenScreen
    tokenPlaceholder: 'Enter Fox Call Token',
    tokenHint: 'Get the token from Telegram bot',
  },
};

let currentLang = 'ar';

export async function initLang() {
  try {
    const saved = await getItemAsync(LANG_KEY);
    if (saved && translations[saved]) {
      currentLang = saved;
    }
  } catch {}
}

export function getLang() {
  return currentLang;
}

export async function setLang(lang) {
  if (translations[lang]) {
    currentLang = lang;
    try {
      await setItemAsync(LANG_KEY, lang);
    } catch {}
  }
}

export function toggleLang() {
  const newLang = currentLang === 'ar' ? 'en' : 'ar';
  setLang(newLang);
  return newLang;
}

export function t(key, params = {}) {
  const dict = translations[currentLang] || translations['ar'];
  let text = dict[key] || translations['ar'][key] || key;
  Object.keys(params).forEach(k => {
    text = text.replace(`{${k}}`, params[k]);
  });
  return text;
}

export function isRTL() {
  return currentLang === 'ar';
}
