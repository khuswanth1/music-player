import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { getAccessToken, refreshSession } from '../api/client'
import { RealtimeClient } from '../api/realtime'
import { useAuth } from './AuthContext'

const RealtimeContext = createContext(null)

export function RealtimeProvider({ children }) {
  const { status: authStatus, refreshUser } = useAuth()
  const [status, setStatus] = useState('offline')
  const clientRef = useRef(null)

  if (!clientRef.current) {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    clientRef.current = new RealtimeClient({
      url: `${proto}://${window.location.host}/api/v1/ws`,
      getToken: getAccessToken,
      onStatus: (s) => {
        if (s === 'unauthenticated') {
          refreshSession().catch(() => {}) // next reconnect picks up the new token
          return
        }
        setStatus(s)
      },
    })
  }

  useEffect(() => {
    const client = clientRef.current
    if (authStatus === 'authenticated') client.connect()
    else client.disconnect()
    return () => client.disconnect()
  }, [authStatus])

  // Personal channel: e.g. subscription changes made in another tab or by a webhook.
  useEffect(() => {
    if (authStatus !== 'authenticated') return undefined
    return clientRef.current.subscribe('user:me', (msg) => {
      if (msg.type === 'subscription.updated') refreshUser().catch(() => {})
    })
  }, [authStatus, refreshUser])

  // Stable identities, so components' subscriptions don't churn when the connection status changes.
  const subscribe = useCallback((channel, handler) => clientRef.current.subscribe(channel, handler), [])
  const send = useCallback((message) => clientRef.current.send(message), [])
  const value = useMemo(() => ({ status, subscribe, send }), [status, subscribe, send])

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>
}

export function useRealtime() {
  return useContext(RealtimeContext)
}

/** Subscribe to a channel for the lifetime of a component. */
export function useChannel(channel, handler) {
  const { subscribe } = useRealtime()
  const handlerRef = useRef(handler)
  handlerRef.current = handler
  useEffect(() => {
    if (!channel) return undefined
    return subscribe(channel, (msg) => handlerRef.current(msg))
  }, [channel, subscribe])
}
