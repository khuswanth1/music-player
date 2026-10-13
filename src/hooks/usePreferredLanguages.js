import { useCallback, useMemo } from 'react'
import { musicApi } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'

/** The signed-in user's preferred languages, with a toggle that saves to the server. */
export function usePreferredLanguages() {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const saved = user?.preferred_languages
  const preferred = useMemo(() => saved || [], [saved])
  const toggle = useCallback(async (code) => {
    const next = preferred.includes(code) ? preferred.filter((c) => c !== code) : [...preferred, code]
    try {
      const res = await musicApi.setMyLanguages(next)
      setUser((u) => ({ ...u, preferred_languages: res.languages }))
    } catch (err) {
      toast.apiError(err)
    }
  }, [preferred, setUser, toast])
  return { preferred, toggle }
}
