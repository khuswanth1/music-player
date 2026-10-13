import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Runs `fn(signal)` whenever `deps` change. Aborts stale requests so a slow
 * response can never overwrite a newer one.
 */
export function useApi(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const fnRef = useRef(fn)
  fnRef.current = fn
  const controllerRef = useRef(null)

  const run = useCallback(async ({ silent = false } = {}) => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    if (!silent) setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await fnRef.current(controller.signal)
      if (!controller.signal.aborted) setState({ data, error: null, loading: false })
    } catch (error) {
      if (!controller.signal.aborted && error.name !== 'AbortError') setState({ data: null, error, loading: false })
    }
  }, [])

  useEffect(() => {
    run()
    return () => controllerRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  const setData = useCallback((updater) => {
    setState((s) => ({ ...s, data: typeof updater === 'function' ? updater(s.data) : updater }))
  }, [])

  return { ...state, reload: run, setData }
}

export function useDebounce(value, delay = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}
