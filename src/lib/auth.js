/** Password rules shown on the sign-up form; the server enforces the same ones. */
export function passwordRules(value = '') {
  return [
    { id: 'letter', label: '1 letter', ok: /\p{L}/u.test(value) },
    { id: 'number', label: '1 number or special character (example: # ? ! &)', ok: /[\d\W_]/.test(value) },
    { id: 'length', label: '10 characters', ok: value.length >= 10 },
  ]
}

export const passwordValid = (value) => passwordRules(value).every((r) => r.ok)

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

/** "khuswanth5@gmail.com" -> "k******5@g***l.com": enough to recognise, not to read. */
export function maskEmail(email = '') {
  const [local = '', domain = ''] = email.trim().split('@')
  const dot = domain.lastIndexOf('.')
  const name = dot > 0 ? domain.slice(0, dot) : domain
  const tld = dot > 0 ? domain.slice(dot) : ''
  const hide = (s) => (s.length <= 2 ? `${s[0] || ''}*` : `${s[0]}${'*'.repeat(Math.min(6, s.length - 2))}${s[s.length - 1]}`)
  return `${hide(local)}@${hide(name)}${tld}`
}

export const MIN_AGE = 13

/** Validates year/month/day inputs. Returns { date: 'YYYY-MM-DD' } or { error }. */
export function checkBirthDate({ year, month, day }, today = new Date()) {
  const y = Number(year)
  const m = Number(month)
  const d = Number(day)
  if (!year || !/^\d{4}$/.test(String(year))) return { error: 'Enter the year your birth date falls in, using four digits (e.g. 1990).', field: 'year' }
  if (!month) return { error: 'Select the month your birth date falls in.', field: 'month' }
  if (!day || !/^\d{1,2}$/.test(String(day))) return { error: 'Enter the day of your birth date as a number.', field: 'day' }
  const date = new Date(Date.UTC(y, m - 1, d))
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) {
    return { error: 'Enter a valid date of birth.', field: 'day' }
  }
  let age = today.getFullYear() - y
  if (today.getMonth() + 1 < m || (today.getMonth() + 1 === m && today.getDate() < d)) age -= 1
  if (date > today || age > 120) return { error: 'Enter a valid date of birth.', field: 'year' }
  if (age < MIN_AGE) return { error: `You must be at least ${MIN_AGE} to create an account.`, field: 'year' }
  return { date: `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}` }
}

export const GENDERS = [
  { id: 'man', label: 'Man' }, { id: 'woman', label: 'Woman' }, { id: 'non_binary', label: 'Non-binary' },
  { id: 'something_else', label: 'Something else' }, { id: 'prefer_not_to_say', label: 'Prefer not to say' },
]

/** Where a server field error belongs in the multi-step sign-up form. */
export const SIGNUP_FIELD_STEP = { email: 0, password: 1, display_name: 2, date_of_birth: 2, gender: 2 }
