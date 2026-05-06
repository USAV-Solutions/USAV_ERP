export type UserRole = 'ADMIN' | 'WAREHOUSE_OP' | 'SALES_REP' | 'ACCOUNTANT'

export interface User {
  id: number
  username: string
  role: UserRole
  is_active: boolean
}

export interface AuthResponse {
  access_token: string
  token_type: string
}

export interface LoginCredentials {
  username: string
  password: string
}
