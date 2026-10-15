import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RequireAuth } from '../components/layout/AppLayout'
import { needsOnboarding } from '../context/AuthContext'
import OnboardingPage from '../pages/OnboardingPage'

const api = vi.hoisted(() => ({
  genres: vi.fn(), catalogArtists: vi.fn(), searchArtists: vi.fn(), artistPhotos: vi.fn(), follow: vi.fn(), setMyLanguages: vi.fn(),
}))
vi.mock('../api/endpoints', () => ({
  catalogApi: { genres: api.genres },
  worldApi: { catalogArtists: api.catalogArtists, searchArtists: api.searchArtists, artistPhotos: api.artistPhotos },
  libraryApi: { follow: api.follow },
  musicApi: { setMyLanguages: api.setMyLanguages },
}))
const auth = vi.hoisted(() => ({ value: null }))
vi.mock('../context/AuthContext', async (importOriginal) => ({ ...(await importOriginal()), useAuth: () => auth.value }))
vi.mock('../context/PlayerContext', () => ({ usePlayer: () => ({}) }))
vi.mock('../lib/languages', () => ({
  useLanguages: () => [
    { code: 'te', name: 'Telugu', native_name: 'Telugu-native', featured: true, playable_count: 5 },
    { code: 'hi', name: 'Hindi', native_name: 'Hindi-native', featured: true, playable_count: 5 },
  ],
}))

const completeOnboarding = vi.fn()
const setup = (user) => {
  auth.value = { user, status: 'authenticated', completeOnboarding }
}
const renderFlow = () => render(
  <MemoryRouter initialEntries={['/welcome']}>
    <Routes>
      <Route path="/welcome" element={<OnboardingPage />} />
      <Route path="/" element={<p>Home screen</p>} />
    </Routes>
  </MemoryRouter>,
)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setup({ id: 'u1', display_name: 'Asha Rao', onboarded: false })
  api.genres.mockResolvedValue([{ id: 1, name: 'Rock', slug: 'rock', color: '#e13300' }, { id: 2, name: 'Pop', slug: 'pop', color: '#8d67ab' }])
  api.catalogArtists.mockResolvedValue([{ id: 'a1', name: 'Singer One' }, { id: 'a2', name: 'Singer Two' }, { id: 'j1', name: '#SWAMI_UPLOADS' }])
  api.searchArtists.mockResolvedValue({ items: [{ id: 'old1', name: 'Ghantasala' }, { id: 'junk', name: '#UPLOAD_CHANNEL' }], providers: [] })
  api.artistPhotos.mockResolvedValue({ a1: 'https://upload.test/one.jpg' })
  api.follow.mockResolvedValue({})
  api.setMyLanguages.mockResolvedValue({ languages: ['te'] })
})

describe('onboarding flow', () => {
  it('saves the chosen languages, genres and followed artists, then opens home', async () => {
    renderFlow()
    expect(screen.getByRole('heading', { name: /Welcome, Asha! Which languages/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Continue/ })).toBeDisabled() // nothing picked yet: Skip is the way on
    await userEvent.click(screen.getByRole('button', { name: /Telugu/ }))
    await userEvent.click(screen.getByRole('button', { name: /Continue \(1\)/ }))
    expect(api.setMyLanguages).toHaveBeenCalledWith(['te'])

    await userEvent.click(await screen.findByRole('button', { name: 'Rock' }))
    await userEvent.click(screen.getByRole('button', { name: /Continue \(1\)/ }))

    expect(await screen.findByRole('button', { name: 'Singer One' })).toBeInTheDocument()
    expect(api.catalogArtists).toHaveBeenCalledWith({ language: 'te', limit: 30 }, expect.anything()) // artists follow the language pick
    await userEvent.click(screen.getByRole('button', { name: 'Singer One' }))
    await userEvent.click(screen.getByRole('button', { name: /Follow 1/ }))

    expect(api.follow).toHaveBeenCalledWith('a1')
    expect(completeOnboarding).toHaveBeenCalledWith(['rock'])
    expect(await screen.findByText('Home screen')).toBeInTheDocument()
  })

  it('lets every step be skipped and still reaches home without saving anything', async () => {
    renderFlow()
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    await screen.findByRole('heading', { name: /music journey/ })
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    await screen.findByRole('heading', { name: /Follow a few singers/ })
    expect(api.catalogArtists).toHaveBeenCalledWith({ language: undefined, limit: 48 }, expect.anything()) // no languages: general artists
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))

    expect(await screen.findByText('Home screen')).toBeInTheDocument()
    expect(api.setMyLanguages).not.toHaveBeenCalled()
    expect(api.follow).not.toHaveBeenCalled()
    expect(completeOnboarding).toHaveBeenCalledWith(undefined)
  })

  it('keeps earlier picks when only the last step is skipped, but follows nobody', async () => {
    renderFlow()
    await userEvent.click(screen.getByRole('button', { name: /Hindi/ }))
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Pop' }))
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Singer Two' }))
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))

    expect(api.setMyLanguages).toHaveBeenCalledWith(['hi'])
    expect(api.follow).not.toHaveBeenCalled()
    expect(completeOnboarding).toHaveBeenCalledWith(['pop'])
    expect(await screen.findByText('Home screen')).toBeInTheDocument()
  })

  it('does not apply a step’s choices when that step is skipped', async () => {
    renderFlow()
    await userEvent.click(screen.getByRole('button', { name: /Hindi/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Skip' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Skip' }))
    expect(api.setMyLanguages).not.toHaveBeenCalled()
  })

  it('still lets people through when genres or artists fail to load', async () => {
    api.genres.mockRejectedValue(new Error('down'))
    api.catalogArtists.mockRejectedValue(new Error('down'))
    renderFlow()
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    expect(await screen.findByText(/load genres/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    expect(await screen.findByText(/load artists/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    expect(await screen.findByText('Home screen')).toBeInTheDocument()
  })
})

describe('singer step', () => {
  const toArtists = async (lang = /Telugu/) => {
    renderFlow()
    await userEvent.click(screen.getByRole('button', { name: lang }))
    await userEvent.click(screen.getByRole('button', { name: /Continue/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Skip' }))
    await screen.findByRole('button', { name: 'Singer One' })
  }

  it('hides upload-channel style names and offers classic voices for the chosen language', async () => {
    await toArtists()
    expect(screen.queryByRole('button', { name: /SWAMI/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ghantasala' })).toBeInTheDocument() // a legend chip for Telugu
  })

  it('finds and follows an older singer through search', async () => {
    await toArtists()
    await userEvent.click(screen.getByRole('button', { name: 'Ghantasala' }))
    await waitFor(() => expect(api.searchArtists).toHaveBeenCalledWith({ q: 'Ghantasala' }, expect.anything())) // after the typing debounce
    expect(await screen.findByRole('button', { name: 'Ghantasala', pressed: false })).toBeInTheDocument()
    expect(screen.queryByText('#UPLOAD_CHANNEL')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Ghantasala', pressed: false }))
    await userEvent.click(screen.getByRole('button', { name: /Follow 1/ }))
    expect(api.follow).toHaveBeenCalledWith('old1')
  })
})

describe('singer photos', () => {
  it('shows a looked-up portrait, never album artwork, and asks only for artists without a photo', async () => {
    api.catalogArtists.mockResolvedValue([
      { id: 'a1', name: 'Singer One', image_fallback: 'https://cdn.test/album-cover.jpg' },
      { id: 'a2', name: 'Singer Two', image_url: 'https://cdn.test/photo-two.jpg' },
    ])
    renderFlow()
    await userEvent.click(screen.getByRole('button', { name: 'Skip' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Skip' }))
    const one = await screen.findByRole('button', { name: 'Singer One' })
    await waitFor(() => expect(one.querySelector('img')).toHaveAttribute('src', 'https://upload.test/one.jpg'))
    expect(api.artistPhotos).toHaveBeenCalledWith(['a1']) // a2 already has one
    expect(document.querySelector('img[src*="album-cover"]')).toBeNull()
    expect(screen.getByRole('button', { name: 'Singer Two' }).querySelector('img')).toHaveAttribute('src', 'https://cdn.test/photo-two.jpg')
  })
})

describe('when onboarding is offered', () => {
  it('only to new, not-yet-onboarded accounts, and never again once done on this device', () => {
    expect(needsOnboarding(null)).toBe(false)
    expect(needsOnboarding({ id: 'u1' })).toBe(false) // unknown (older server): treated as done
    expect(needsOnboarding({ id: 'u1', onboarded: true })).toBe(false)
    expect(needsOnboarding({ id: 'u1', onboarded: false })).toBe(true)
    localStorage.setItem('wavely.onboarded.u1', '1')
    expect(needsOnboarding({ id: 'u1', onboarded: false })).toBe(false) // server call failed, but it was finished here
  })

  const renderGuarded = (user, path) => {
    setup(user)
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/welcome" element={<RequireAuth onboarding><p>Welcome screen</p></RequireAuth>} />
          <Route path="/" element={<RequireAuth><p>Protected home</p></RequireAuth>} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('sends a brand-new account from home to the welcome screen', async () => {
    renderGuarded({ id: 'u2', onboarded: false }, '/')
    expect(await screen.findByText('Welcome screen')).toBeInTheDocument()
  })

  it('goes straight to home for returning users', async () => {
    renderGuarded({ id: 'u3', onboarded: true }, '/')
    expect(await screen.findByText('Protected home')).toBeInTheDocument()
  })

  it('does not show /welcome to someone who already finished', async () => {
    renderGuarded({ id: 'u3', onboarded: true }, '/welcome')
    await waitFor(() => expect(screen.getByText('Protected home')).toBeInTheDocument())
  })
})
