import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { onSessionExpired, refreshSession, setAccessToken } from '../api/client'
import { authApi, meApi } from '../api/endpoints'

const AuthContext = createContext(null)

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

  const value = useMemo(() => ({
    user, status, login, loginWithCode, register, logout, resume, refreshUser, setUser, acceptSession,
    can: (perm) => Boolean(user?.permissions?.includes(perm)),
  }), [user, status, login, loginWithCode, register, logout, resume, refreshUser, acceptSession])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
