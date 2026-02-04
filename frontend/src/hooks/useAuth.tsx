import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import axios from 'axios'
import { User, UserRole, LoginCredentials, AuthResponse } from '../types/auth'

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (credentials: LoginCredentials) => Promise<void>
  loginWithToken: (token: string) => Promise<void>
  logout: () => void
  hasRole: (roles: UserRole[]) => boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

// Decode JWT to extract user info
function decodeToken(token: string): { sub: string; role: UserRole; username?: string } | null {
  try {
    const base64Url = token.split('.')[1]
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    )
    return JSON.parse(jsonPayload)
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    // Check for existing token on mount
    const token = localStorage.getItem('access_token')
    const savedUser = localStorage.getItem('user')
    
    if (token && savedUser) {
      try {
        setUser(JSON.parse(savedUser))
      } catch {
        localStorage.removeItem('access_token')
        localStorage.removeItem('user')
      }
    }
    setIsLoading(false)
  }, [])

  const login = async (credentials: LoginCredentials) => {
    // FastAPI expects form data for OAuth2
    const formData = new URLSearchParams()
    formData.append('username', credentials.username)
    formData.append('password', credentials.password)

    const response = await axios.post<AuthResponse>('/api/v1/auth/token', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    })

    const { access_token } = response.data
    localStorage.setItem('access_token', access_token)

    // Decode token to get user info
    const decoded = decodeToken(access_token)
    if (decoded) {
      const userData: User = {
        id: parseInt(decoded.sub) || 0,
        username: decoded.username || decoded.sub,
        role: decoded.role,
        is_active: true,
      }
      setUser(userData)
      localStorage.setItem('user', JSON.stringify(userData))
    }
  }

  const loginWithToken = async (token: string) => {
    localStorage.setItem('access_token', token)

    // Decode token to get user info
    const decoded = decodeToken(token)
    if (decoded) {
      const userData: User = {
        id: parseInt(decoded.sub) || 0,
        username: decoded.username || decoded.sub,
        role: decoded.role,
        is_active: true,
      }
      setUser(userData)
      localStorage.setItem('user', JSON.stringify(userData))
    }
  }

  const logout = () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('user')
    setUser(null)
  }

  const hasRole = (roles: UserRole[]) => {
    if (!user) return false
    return roles.includes(user.role)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        loginWithToken,
        logout,
        hasRole,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
