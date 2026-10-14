import { NavLink } from 'react-router'
import { Clapperboard, Home, Languages, Library, Mic2, Search } from 'lucide-react'

const items = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/languages', label: 'Languages', icon: Languages },
  { to: '/podcasts', label: 'Podcasts', icon: Mic2 },
  { to: '/movies', label: 'Movies', icon: Clapperboard },
  { to: '/library', label: 'Library', icon: Library },
]

export default function MobileNav() {
  return (
    <nav aria-label="Main navigation" className="grid grid-cols-6 border-t border-line bg-black/95 md:hidden">
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end}
          className={({ isActive }) => `flex flex-col items-center gap-1 py-2 text-[11px] ${isActive ? 'text-white' : 'text-muted'}`}>
          <Icon className="size-6" /> {label}
        </NavLink>
      ))}
    </nav>
  )
}
