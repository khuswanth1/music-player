import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { checkBirthDate, maskEmail, passwordRules, passwordValid } from '../lib/auth'
import { LoginPage, RegisterPage } from '../pages/AuthPages'

const { auth, authApi } = vi.hoisted(() => ({
  auth: { status: 'anonymous', login: vi.fn(), loginWithCode: vi.fn(), register: vi.fn() },
  authApi: { providers: vi.fn(), loginCode: vi.fn(), forgot: vi.fn(), reset: vi.fn() },
}))
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../api/endpoints', () => ({ authApi }))

beforeEach(() => {
  vi.clearAllMocks()
  authApi.providers.mockResolvedValue({ password: true, google: false })
  authApi.loginCode.mockResolvedValue({ message: 'sent' })
})

const page = (el) => render(<MemoryRouter>{el}</MemoryRouter>)

describe('auth helpers', () => {
  it('checks passwords like the server', () => {
    expect(passwordRules('abc').map((r) => r.ok)).toEqual([true, false, false])
    expect(passwordValid('harmony-123')).toBe(true)
    expect(passwordValid('abcdefghijk')).toBe(false)
    expect(passwordValid('1234567890!')).toBe(false)
  })

  it('masks emails', () => {
    expect(maskEmail('khuswanth5@gmail.com')).toBe('k******5@g***l.com')
    expect(maskEmail('al@x.io')).toBe('a*@x*.io')
  })

  it('validates birth dates and the minimum age', () => {
    const today = new Date(2026, 9, 13)
    expect(checkBirthDate({ year: '2003', month: '6', day: '6' }, today)).toEqual({ date: '2003-06-06' })
    expect(checkBirthDate({ year: '2003', month: '2', day: '30' }, today).error).toMatch(/valid date/)
    expect(checkBirthDate({ year: '2015', month: '1', day: '1' }, today).error).toMatch(/at least 13/)
    expect(checkBirthDate({ year: '03', month: '1', day: '1' }, today).error).toMatch(/four digits/)
  })
})

describe('sign-up flow', () => {
  it('walks email → password → about you → terms and submits everything', async () => {
    const user = userEvent.setup()
    auth.register.mockResolvedValue({})
    page(<RegisterPage />)

    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Please enter your email address.')
    await user.type(screen.getByLabelText('Email address'), 'khuswanth5@gmail.com')
    await user.click(screen.getByRole('button', { name: 'Next' }))

    expect(screen.getByText('Step 1 of 3')).toBeInTheDocument()
    const next = screen.getByRole('button', { name: 'Next' })
    await user.type(screen.getByLabelText('Password'), 'short')
    expect(next).toBeDisabled()
    await user.type(screen.getByLabelText('Password'), '-pass-12')
    expect(screen.getByText('10 characters').closest('li')).toHaveTextContent('(done)')
    await user.click(next)

    expect(screen.getByText('Step 2 of 3')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Enter a name for your profile.')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^Name/), 'Khuswanth')
    await user.type(screen.getByLabelText('Year'), '2003')
    await user.selectOptions(screen.getByLabelText('Month'), '6')
    await user.type(screen.getByLabelText('Day'), '06')
    await user.click(screen.getByLabelText('Man'))
    await user.click(screen.getByRole('button', { name: 'Next' }))

    expect(screen.getByText('Step 3 of 3')).toBeInTheDocument()
    await user.click(screen.getByLabelText(/prefer not to receive marketing/))
    await user.click(screen.getByRole('button', { name: 'Sign up' }))
    expect(auth.register).toHaveBeenCalledWith({
      email: 'khuswanth5@gmail.com', password: 'short-pass-12', display_name: 'Khuswanth', date_of_birth: '2003-06-06',
      gender: 'man', marketing_emails: false,
    })
  })

  it('sends people back to the email step when the address is taken', async () => {
    const user = userEvent.setup()
    auth.register.mockRejectedValue(Object.assign(new Error('taken'), { code: 'email_taken', status: 409 }))
    page(<RegisterPage />)
    await user.type(screen.getByLabelText('Email address'), 'a@b.co')
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await user.type(screen.getByLabelText('Password'), 'harmony-123')
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await user.type(screen.getByLabelText(/^Name/), 'A')
    await user.type(screen.getByLabelText('Year'), '1990')
    await user.selectOptions(screen.getByLabelText('Month'), '1')
    await user.type(screen.getByLabelText('Day'), '1')
    await user.click(screen.getByLabelText('Prefer not to say'))
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await user.click(screen.getByRole('button', { name: 'Sign up' }))
    expect(screen.getByRole('alert')).toHaveTextContent('already linked to an existing account')
    expect(screen.getByLabelText('Email address')).toHaveValue('a@b.co')
  })
})

describe('log-in flow', () => {
  it('emails a code and signs in when all six digits are typed', async () => {
    const user = userEvent.setup()
    auth.loginWithCode.mockResolvedValue({})
    page(<LoginPage />)
    await user.type(screen.getByLabelText('Email'), 'khuswanth5@gmail.com')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(authApi.loginCode).toHaveBeenCalledWith('khuswanth5@gmail.com')
    expect(screen.getByRole('heading')).toHaveTextContent('Enter the code we sent to k******5@g***l.com')
    expect(screen.getByRole('button', { name: /Resend code in/ })).toBeDisabled()

    await user.type(screen.getByLabelText('Digit 1'), '123456')
    expect(auth.loginWithCode).toHaveBeenCalledWith('khuswanth5@gmail.com', '123456')
  })

  it('offers a password instead of a code', async () => {
    const user = userEvent.setup()
    auth.login.mockRejectedValue(Object.assign(new Error('bad'), { status: 401 }))
    page(<LoginPage />)
    await user.type(screen.getByLabelText('Email'), 'a@b.co')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click(screen.getByRole('button', { name: 'Log in with a password' }))
    await user.type(screen.getByLabelText('Password'), 'wrong-pass-1')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(auth.login).toHaveBeenCalledWith('a@b.co', 'wrong-pass-1')
    expect(screen.getByRole('alert')).toHaveTextContent('Incorrect email or password.')
  })
})
