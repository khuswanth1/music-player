import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { onSessionExpired, refreshSession, setAccessToken } from '../api/client'
import { authApi, meApi } from '../api/endpoints'

const AuthContext = createContext(null)
const onboardedKey = (id) => `wavely.onboarded.${id}`

/** True once onboarding was finished or skipped, here or on the server, so nobody is asked twice. */
export function needsOnboarding(user) {
  if (!user || user.onboarded !== false) return false
  try {
    return !localStorage.getItem(onboardedKey(user.id))
  } catch {
    return true
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('loading') // loading | authenticated | anonymous

  const acceptSession = useCallback((data) => {
    setAccessToken(data.access_token)
    setUser(data.user)
    setStatus('authenticated')
    return data.user
  }, [])

  // On load, try to resume the session from the httpOnly refresh cookie.
  useEffect(() => {
    refreshSession()
      .then(acceptSession)
      .catch(() => setStatus('anonymous'))
    return onSessionExpired(() => {
      setUser(null)
      setStatus('anonymous')
    })
  }, [acceptSession])

  const login = useCallback(async (email, password) => acceptSession(await authApi.login(email, password)), [acceptSession])
  const loginWithCode = useCallback(async (email, code) => acceptSession(await authApi.verifyLoginCode(email, code)), [acceptSession])
  const register = useCallback(async (data) => acceptSession(await authApi.register(data)), [acceptSession])
  const resume = useCallback(async () => acceptSession(await refreshSession()), [acceptSession])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setAccessToken(null)
      setUser(null)
      setStatus('anonymous')
    }
  }, [])

  const refreshUser = useCallback(async () => {
    const me = await meApi.get()
    setUser(me)
    return me
  }, [])

  // Finish or skip onboarding: the app moves on immediately; the server is told in the background. The local flag keeps
  // the screens from coming back on this device even if that request fails.
  const completeOnboarding = useCallback((genres) => {
    const id = user?.id
    if (!id) return
    try {
      localStorage.setItem(onboardedKey(id), '1')
    } catch { /* private mode: the in-memory flag below still holds for this session */ }
    setUser((u) => (u ? { ...u, onboarded: true, ...(genres ? { preferred_genres: genres } : {}) } : u))
    meApi.completeOnboarding(genres).catch(() => meApi.completeOnboarding(genres).catch(() => {}))
  }, [user?.id])

  const value = useMemo(() => ({
    user, status, completeOnboarding, login, loginWithCode, register, logout, resume, refreshUser, setUser, acceptSession,
    can: (perm) => Boolean(user?.permissions?.includes(perm)),
  }), [user, status, completeOnboarding, login, loginWithCode, register, logout, resume, refreshUser, acceptSession])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
