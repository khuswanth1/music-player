import { NavLink } from 'react-router'
import { Home, Languages, Library, Search, Users } from 'lucide-react'

const items = [
  { to: '/', label: 'Home', icon: Home, end: true },
  { to: '/search', label: 'Search', icon: Search },
  { to: '/languages', label: 'Languages', icon: Languages },
  { to: '/library', label: 'Library', icon: Library },
  { to: '/sessions', label: 'Together', icon: Users },
]

export default function MobileNav() {
  return (
    <nav aria-label="Main navigation" className="grid grid-cols-5 border-t border-line bg-black/95 md:hidden">
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end}
          className={({ isActive }) => `flex flex-col items-center gap-1 py-2 text-[11px] ${isActive ? 'text-white' : 'text-muted'}`}>
          <Icon className="size-6" /> {label}
        </NavLink>
      ))}
    </nav>
  )
}
