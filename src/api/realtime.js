// WebSocket client: auth-first handshake, heartbeat, reconnect with backoff, and
// ref-counted channel subscriptions that are replayed after every reconnect.

export class RealtimeClient {
  constructor({ url, getToken, onStatus }) {
    this.url = url
    this.getToken = getToken
    this.onStatus = onStatus || (() => {})
    this.ws = null
    this.handlers = new Map() // channel -> Set<fn>
    this.attempt = 0
    this.closedByUser = false
    this.ready = false
    this.lastMessageAt = 0
    this.watchdog = null
    this.reconnectTimer = null
    this.pending = []
  }

  connect() {
    this.closedByUser = false
    clearTimeout(this.reconnectTimer)
    const token = this.getToken()
    if (!token) return
    this.onStatus('connecting')
    const ws = new WebSocket(this.url)
    this.ws = ws
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }))
    ws.onmessage = (event) => this.#onMessage(event)
    ws.onclose = (event) => this.#onClose(event)
    ws.onerror = () => {} // onclose follows and handles reconnection
  }

  disconnect() {
    this.closedByUser = true
    clearTimeout(this.reconnectTimer)
    clearInterval(this.watchdog)
    this.ws?.close(1000)
    this.ws = null
    this.ready = false
    this.onStatus('offline')
  }

  send(message) {
    if (this.ready && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
      return true
    }
    this.pending.push(message)
    return false
  }

  /** Subscribe to a channel; returns an unsubscribe function. */
  subscribe(channel, handler) {
    let set = this.handlers.get(channel)
    const local = channel.startsWith('*') // client-side pseudo-channels, e.g. '*errors'
    if (!set) {
      set = new Set()
      this.handlers.set(channel, set)
      if (!local) this.send({ type: 'subscribe', channel })
    }
    set.add(handler)
    return () => {
      set.delete(handler)
      if (set.size === 0) {
        this.handlers.delete(channel)
        if (this.ready && !local) this.send({ type: 'unsubscribe', channel })
      }
    }
  }

  #onMessage(event) {
    this.lastMessageAt = Date.now()
    let msg
    try {
      msg = JSON.parse(event.data)
    } catch {
      return
    }
    if (msg.type === 'ready') {
      this.ready = true
      this.userId = msg.user_id
      this.attempt = 0
      this.onStatus('online')
      // Replay subscriptions (server state is lost on reconnect), then anything queued while offline.
      const subs = [...this.handlers.keys()].filter((c) => !c.startsWith('*')).map((channel) => ({ type: 'subscribe', channel }))
      const queued = this.pending.filter((m) => m.type !== 'subscribe' && m.type !== 'unsubscribe')
      this.pending = []
      for (const m of [...subs, ...queued]) this.ws.send(JSON.stringify(m))
      const interval = (msg.heartbeat_interval || 25) * 1000
      clearInterval(this.watchdog)
      this.watchdog = setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: 'ping' }))
        if (Date.now() - this.lastMessageAt > interval * 2.5) this.ws?.close(4000, 'stale') // silent socket
      }, interval)
      return
    }
    if (msg.type === 'ping') {
      this.ws?.send(JSON.stringify({ type: 'pong' }))
      return
    }
    // The server canonicalises 'user:me' to 'user:<id>'.
    const channel = msg.channel === `user:${this.userId}` ? 'user:me' : msg.channel
    if (channel && this.handlers.has(channel)) {
      for (const fn of this.handlers.get(channel)) fn(msg)
    }
    if (msg.type === 'error') {
      for (const fn of this.handlers.get('*errors') || []) fn(msg)
    }
  }

  #onClose(event) {
    clearInterval(this.watchdog)
    this.ready = false
    this.ws = null
    if (this.closedByUser) return
    this.onStatus('offline')
    if (event.code === 4401) {
      // Token expired or invalid: the auth layer refreshes it, then we reconnect.
      this.onStatus('unauthenticated')
    }
    const delay = Math.min(30000, 1000 * 2 ** this.attempt) * (0.75 + Math.random() * 0.5)
    this.attempt += 1
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }
}
