import { Suspense, lazy } from 'react'
import { BrowserRouter, Link, Route, Routes } from 'react-router'
import AppLayout, { RequireAuth } from './components/layout/AppLayout'
import { EmptyState, Spinner } from './components/ui'
import { AuthProvider } from './context/AuthContext'
import { LibraryProvider } from './context/LibraryContext'
import { PlayerProvider } from './context/PlayerContext'
import { RealtimeProvider } from './context/RealtimeContext'
import { SessionProvider } from './context/SessionContext'
import { SpotifyProvider } from './context/SpotifyContext'
import { ToastProvider } from './context/ToastContext'
import { AuthCallbackPage, ForgotPasswordPage, LoginPage, RegisterPage, ResetPasswordPage } from './pages/AuthPages'
import { AlbumPage, ArtistPage, GenrePage } from './pages/CatalogPages'
import HomePage from './pages/HomePage'
import PlaylistPage, { HistoryPage, JoinPlaylistPage, LibraryPage, LikedSongsPage } from './pages/PlaylistPage'
import SearchPage from './pages/SearchPage'
import SpotifyCallbackPage from './pages/SpotifyCallbackPage'
import AdminLayout, { RequirePermission } from './pages/admin/AdminLayout'

// Rarely-visited pages load on demand so the first screen ships less JavaScript.
const named = (loader, name) => lazy(() => loader().then((m) => ({ default: m[name] })))
const MixPage = lazy(() => import('./pages/MixPage'))
const OnboardingPage = lazy(() => import('./pages/OnboardingPage'))
const AccountPage = named(() => import('./pages/AccountPages'), 'AccountPage')
const DevCheckoutPage = named(() => import('./pages/AccountPages'), 'DevCheckoutPage')
const PremiumPage = named(() => import('./pages/AccountPages'), 'PremiumPage')
const ChartPage = named(() => import('./pages/ChartsPages'), 'ChartPage')
const ChartsPage = named(() => import('./pages/ChartsPages'), 'ChartsPage')
const SourcesPage = named(() => import('./pages/ChartsPages'), 'SourcesPage')
const ArtistsPage = lazy(() => import('./pages/ArtistsPage'))
const MoviesPage = named(() => import('./pages/MoviePages'), 'MoviesPage')
const SoundtrackPage = named(() => import('./pages/MoviePages'), 'SoundtrackPage')
const PodcastPage = named(() => import('./pages/PodcastPages'), 'PodcastPage')
const PodcastsPage = named(() => import('./pages/PodcastPages'), 'PodcastsPage')
const PrivateAlbumPage = named(() => import('./pages/PrivateAlbumPages'), 'PrivateAlbumPage')
const PrivateAlbumsPage = named(() => import('./pages/PrivateAlbumPages'), 'PrivateAlbumsPage')
const SharedAlbumPage = named(() => import('./pages/PrivateAlbumPages'), 'SharedAlbumPage')
const LanguagePage = named(() => import('./pages/LanguagePages'), 'LanguagePage')
const LanguagesPage = named(() => import('./pages/LanguagePages'), 'LanguagesPage')
const AlbumsPage = named(() => import('./pages/WorldPages'), 'AlbumsPage')
const CountriesPage = named(() => import('./pages/WorldPages'), 'CountriesPage')
const CountryPage = named(() => import('./pages/WorldPages'), 'CountryPage')
const SessionsPage = lazy(() => import('./pages/SessionsPage'))
const CatalogAdmin = lazy(() => import('./pages/admin/CatalogAdmin'))
const DashboardPage = lazy(() => import('./pages/admin/DashboardPage'))
const BillingAdmin = named(() => import('./pages/admin/ManagementPages'), 'BillingAdmin')
const PlaylistsAdmin = named(() => import('./pages/admin/ManagementPages'), 'PlaylistsAdmin')
const UsersAdmin = named(() => import('./pages/admin/ManagementPages'), 'UsersAdmin')
const WebhooksAdmin = named(() => import('./pages/admin/ManagementPages'), 'WebhooksAdmin')
const SourcesAdmin = lazy(() => import('./pages/admin/SourcesAdmin'))

function NotFound() {
  return (
    <EmptyState title="Page not found" action={<Link to="/" className="rounded-full bg-white px-5 py-2 text-sm font-bold text-black">Go home</Link>}>
      We couldn&apos;t find the page you were looking for.
    </EmptyState>
  )
}

const guard = (perm, el) => <RequirePermission perm={perm}>{el}</RequirePermission>

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <RealtimeProvider>
            <LibraryProvider>
              <SpotifyProvider>
              <PlayerProvider>
                <SessionProvider>
                  <Suspense fallback={<div className="flex h-dvh items-center justify-center"><Spinner className="size-8 text-accent" /></div>}>
                  <Routes>
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/register" element={<RegisterPage />} />
                    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                    <Route path="/reset-password" element={<ResetPasswordPage />} />
                    <Route path="/auth/callback" element={<AuthCallbackPage />} />
                    <Route path="/welcome" element={<RequireAuth onboarding><OnboardingPage /></RequireAuth>} />
                    <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
                      <Route index element={<HomePage />} />
                      <Route path="mix/:id" element={<MixPage />} />
                      <Route path="search" element={<SearchPage />} />
                      <Route path="library" element={<LibraryPage />} />
                      <Route path="collection/tracks" element={<LikedSongsPage />} />
                      <Route path="history" element={<HistoryPage />} />
                      <Route path="album/:id" element={<AlbumPage />} />
                      <Route path="artist/:id" element={<ArtistPage />} />
                      <Route path="artists" element={<ArtistsPage />} />
                      <Route path="albums" element={<AlbumsPage />} />
                      <Route path="countries" element={<CountriesPage />} />
                      <Route path="country/:code" element={<CountryPage />} />
                      <Route path="podcasts" element={<PodcastsPage />} />
                      <Route path="podcast/:id" element={<PodcastPage />} />
                      <Route path="movies" element={<MoviesPage />} />
                      <Route path="soundtrack/:id" element={<SoundtrackPage />} />
                      <Route path="private-albums" element={<PrivateAlbumsPage />} />
                      <Route path="private-albums/:id" element={<PrivateAlbumPage />} />
                      <Route path="shared/:code" element={<SharedAlbumPage />} />
                      <Route path="genre/:slug" element={<GenrePage />} />
                      <Route path="languages" element={<LanguagesPage />} />
                      <Route path="language/:code" element={<LanguagePage />} />
                      <Route path="charts" element={<ChartsPage />} />
                      <Route path="charts/:id" element={<ChartPage />} />
                      <Route path="sources" element={<SourcesPage />} />
                      <Route path="playlist/:id" element={<PlaylistPage />} />
                      <Route path="playlist/:id/join" element={<JoinPlaylistPage />} />
                      <Route path="sessions" element={<SessionsPage />} />
                      <Route path="account" element={<AccountPage />} />
                      <Route path="spotify/callback" element={<SpotifyCallbackPage />} />
                      <Route path="premium" element={<PremiumPage />} />
                      <Route path="checkout/dev" element={<DevCheckoutPage />} />
                      <Route path="admin" element={<AdminLayout />}>
                        <Route index element={guard('analytics:view', <DashboardPage />)} />
                        <Route path="catalog" element={guard('catalog:write', <CatalogAdmin />)} />
                        <Route path="sources" element={guard('catalog:write', <SourcesAdmin />)} />
                        <Route path="users" element={guard('users:manage', <UsersAdmin />)} />
                        <Route path="playlists" element={guard('playlists:moderate', <PlaylistsAdmin />)} />
                        <Route path="billing" element={guard('billing:manage', <BillingAdmin />)} />
                        <Route path="webhooks" element={guard('webhooks:manage', <WebhooksAdmin />)} />
                      </Route>
                      <Route path="*" element={<NotFound />} />
                    </Route>
                  </Routes>
                  </Suspense>
                </SessionProvider>
              </PlayerProvider>
              </SpotifyProvider>
            </LibraryProvider>
          </RealtimeProvider>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
