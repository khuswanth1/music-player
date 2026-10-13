import { BrowserRouter, Link, Route, Routes } from 'react-router'
import AppLayout, { RequireAuth } from './components/layout/AppLayout'
import { EmptyState } from './components/ui'
import { AuthProvider } from './context/AuthContext'
import { LibraryProvider } from './context/LibraryContext'
import { PlayerProvider } from './context/PlayerContext'
import { RealtimeProvider } from './context/RealtimeContext'
import { SessionProvider } from './context/SessionContext'
import { ToastProvider } from './context/ToastContext'
import { AccountPage, DevCheckoutPage, PremiumPage } from './pages/AccountPages'
import { AuthCallbackPage, ForgotPasswordPage, LoginPage, RegisterPage, ResetPasswordPage } from './pages/AuthPages'
import { AlbumPage, ArtistPage, GenrePage } from './pages/CatalogPages'
import { ChartPage, ChartsPage, SourcesPage } from './pages/ChartsPages'
import HomePage from './pages/HomePage'
import { LanguagePage, LanguagesPage } from './pages/LanguagePages'
import PlaylistPage, { HistoryPage, JoinPlaylistPage, LibraryPage, LikedSongsPage } from './pages/PlaylistPage'
import SearchPage from './pages/SearchPage'
import SessionsPage from './pages/SessionsPage'
import AdminLayout, { RequirePermission } from './pages/admin/AdminLayout'
import CatalogAdmin from './pages/admin/CatalogAdmin'
import DashboardPage from './pages/admin/DashboardPage'
import { BillingAdmin, PlaylistsAdmin, UsersAdmin, WebhooksAdmin } from './pages/admin/ManagementPages'
import SourcesAdmin from './pages/admin/SourcesAdmin'

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
              <PlayerProvider>
                <SessionProvider>
                  <Routes>
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/register" element={<RegisterPage />} />
                    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                    <Route path="/reset-password" element={<ResetPasswordPage />} />
                    <Route path="/auth/callback" element={<AuthCallbackPage />} />
                    <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
                      <Route index element={<HomePage />} />
                      <Route path="search" element={<SearchPage />} />
                      <Route path="library" element={<LibraryPage />} />
                      <Route path="collection/tracks" element={<LikedSongsPage />} />
                      <Route path="history" element={<HistoryPage />} />
                      <Route path="album/:id" element={<AlbumPage />} />
                      <Route path="artist/:id" element={<ArtistPage />} />
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
                </SessionProvider>
              </PlayerProvider>
            </LibraryProvider>
          </RealtimeProvider>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
