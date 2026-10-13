import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { libraryApi, playlistApi } from '../api/endpoints'
import { useAuth } from './AuthContext'
import { useToast } from './ToastContext'

const LibraryContext = createContext(null)

/** Shared library state: the sidebar playlist list and like status that stays in sync across screens. */
export function LibraryProvider({ children }) {
  const { status } = useAuth()
  const toast = useToast()
  const [playlists, setPlaylists] = useState([])
  const [playlistsLoading, setPlaylistsLoading] = useState(true)
  const [likeOverrides, setLikeOverrides] = useState({})

  const refreshPlaylists = useCallback(async () => {
    try {
      setPlaylists(await playlistApi.mine())
    } catch {
      /* the sidebar shows an empty list; pages surface their own errors */
    } finally {
      setPlaylistsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (status === 'authenticated') refreshPlaylists()
    else {
      setPlaylists([])
      setLikeOverrides({})
    }
  }, [status, refreshPlaylists])

  const isLiked = useCallback((song) => likeOverrides[song.id] ?? Boolean(song.liked), [likeOverrides])

  const toggleLike = useCallback(async (song) => {
    const next = !isLiked(song)
    setLikeOverrides((o) => ({ ...o, [song.id]: next })) // optimistic
    try {
      await (next ? libraryApi.like(song.id) : libraryApi.unlike(song.id))
      toast.success(next ? 'Added to Liked Songs' : 'Removed from Liked Songs')
    } catch (err) {
      setLikeOverrides((o) => ({ ...o, [song.id]: !next }))
      toast.apiError(err)
    }
  }, [isLiked, toast])

  const createPlaylist = useCallback(async (data) => {
    const created = await playlistApi.create(data)
    await refreshPlaylists()
    return created
  }, [refreshPlaylists])

  const addToPlaylist = useCallback(async (playlist, songs) => {
    try {
      await playlistApi.addTracks(playlist.id, songs.map((s) => s.id))
      toast.success(`Added to ${playlist.name}`)
      refreshPlaylists()
    } catch (err) {
      toast.apiError(err)
    }
  }, [toast, refreshPlaylists])

  const value = useMemo(() => ({
    playlists, playlistsLoading, refreshPlaylists, createPlaylist, addToPlaylist, isLiked, toggleLike,
    editablePlaylists: playlists,
  }), [playlists, playlistsLoading, refreshPlaylists, createPlaylist, addToPlaylist, isLiked, toggleLike])

  return <LibraryContext.Provider value={value}>{children}</LibraryContext.Provider>
}

export function useLibrary() {
  return useContext(LibraryContext)
}
