import { useState } from 'react'
import {
  Box,
  Typography,
  Paper,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Switch,
  FormControlLabel,
  Alert,
  Snackbar,
  Tooltip,
  CircularProgress,
} from '@mui/material'
import {
  Add,
  Edit,
  Delete,
  Lock,
  CheckCircle,
  Cancel,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../api/axiosClient'

type UserRole = 'ADMIN' | 'WAREHOUSE_OP' | 'SALES_REP' | 'ACCOUNTANT'

interface User {
  id: number
  username: string
  email?: string
  full_name?: string
  seatalk_id?: string
  role: UserRole
  is_active: boolean
  is_superuser: boolean
  last_login?: string
  created_at: string
  updated_at: string
}

interface UserFormData {
  username: string
  email: string
  full_name: string
  password: string
  role: UserRole
  is_active: boolean
}

const initialFormData: UserFormData = {
  username: '',
  email: '',
  full_name: '',
  password: '',
  role: 'WAREHOUSE_OP',
  is_active: true,
}

const getRoleColor = (role: UserRole): 'error' | 'primary' | 'success' | 'warning' => {
  switch (role) {
    case 'ADMIN': return 'error'
    case 'WAREHOUSE_OP': return 'primary'
    case 'SALES_REP': return 'success'
    case 'ACCOUNTANT': return 'warning'
    default: return 'primary'
  }
}

const getRoleLabel = (role: UserRole): string => {
  switch (role) {
    case 'ADMIN': return 'Administrator'
    case 'WAREHOUSE_OP': return 'Warehouse Op'
    case 'SALES_REP': return 'Sales Rep'
    case 'ACCOUNTANT': return 'Accountant'
    default: return role
  }
}

export default function UserManagement() {
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [formData, setFormData] = useState<UserFormData>(initialFormData)
  const [newPassword, setNewPassword] = useState('')
  const [notification, setNotification] = useState<{
    open: boolean
    message: string
    severity: 'success' | 'error'
  }>({ open: false, message: '', severity: 'success' })

  // Fetch users
  const { data: usersData, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const response = await axiosClient.get('/auth/users', {
        params: { limit: 1000 },
      })
      return response.data.items || []
    },
  })

  // Create user mutation
  const createUserMutation = useMutation({
    mutationFn: async (data: UserFormData) => {
      const response = await axiosClient.post('/auth/users', data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setDialogOpen(false)
      showNotification('User created successfully', 'success')
      resetForm()
    },
    onError: (error: any) => {
      showNotification(error.response?.data?.detail || 'Failed to create user', 'error')
    },
  })

  // Update user mutation
  const updateUserMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<UserFormData> }) => {
      const response = await axiosClient.patch(`/auth/users/${id}`, data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setDialogOpen(false)
      showNotification('User updated successfully', 'success')
      resetForm()
    },
    onError: (error: any) => {
      showNotification(error.response?.data?.detail || 'Failed to update user', 'error')
    },
  })

  // Change password mutation
  const changePasswordMutation = useMutation({
    mutationFn: async ({ id, password }: { id: number; password: string }) => {
      const response = await axiosClient.patch(`/auth/users/${id}`, { password })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setPasswordDialogOpen(false)
      setNewPassword('')
      showNotification('Password changed successfully', 'success')
    },
    onError: (error: any) => {
      showNotification(error.response?.data?.detail || 'Failed to change password', 'error')
    },
  })

  // Delete user mutation
  const deleteUserMutation = useMutation({
    mutationFn: async (id: number) => {
      await axiosClient.delete(`/auth/users/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setDeleteDialogOpen(false)
      setSelectedUser(null)
      showNotification('User deleted successfully', 'success')
    },
    onError: (error: any) => {
      showNotification(error.response?.data?.detail || 'Failed to delete user', 'error')
    },
  })

  // Toggle active status mutation
  const toggleActiveMutation = useMutation({
    mutationFn: async ({ id, isActive }: { id: number; isActive: boolean }) => {
      const endpoint = isActive ? `/auth/users/${id}/activate` : `/auth/users/${id}/deactivate`
      const response = await axiosClient.post(endpoint)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      showNotification('User status updated', 'success')
    },
    onError: (error: any) => {
      showNotification(error.response?.data?.detail || 'Failed to update status', 'error')
    },
  })

  const showNotification = (message: string, severity: 'success' | 'error') => {
    setNotification({ open: true, message, severity })
  }

  const resetForm = () => {
    setFormData(initialFormData)
    setSelectedUser(null)
  }

  const handleOpenCreateDialog = () => {
    resetForm()
    setDialogOpen(true)
  }

  const handleOpenEditDialog = (user: User) => {
    setSelectedUser(user)
    setFormData({
      username: user.username,
      email: user.email || '',
      full_name: user.full_name || '',
      password: '',
      role: user.role,
      is_active: user.is_active,
    })
    setDialogOpen(true)
  }

  const handleOpenPasswordDialog = (user: User) => {
    setSelectedUser(user)
    setNewPassword('')
    setPasswordDialogOpen(true)
  }

  const handleOpenDeleteDialog = (user: User) => {
    setSelectedUser(user)
    setDeleteDialogOpen(true)
  }

  const handleSubmit = () => {
    if (selectedUser) {
      // Update existing user (exclude password if empty)
      const updateData: Partial<UserFormData> = {
        email: formData.email || undefined,
        full_name: formData.full_name || undefined,
        role: formData.role,
        is_active: formData.is_active,
      }
      updateUserMutation.mutate({ id: selectedUser.id, data: updateData })
    } else {
      // Create new user
      createUserMutation.mutate(formData)
    }
  }

  const handleChangePassword = () => {
    if (selectedUser && newPassword) {
      changePasswordMutation.mutate({ id: selectedUser.id, password: newPassword })
    }
  }

  const handleDeleteUser = () => {
    if (selectedUser) {
      deleteUserMutation.mutate(selectedUser.id)
    }
  }

  const handleToggleActive = (user: User) => {
    toggleActiveMutation.mutate({ id: user.id, isActive: !user.is_active })
  }

  const users: User[] = usersData || []

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">User Management</Typography>
        <Button
          variant="contained"
          startIcon={<Add />}
          onClick={handleOpenCreateDialog}
        >
          Add User
        </Button>
      </Box>

      {/* Users Table */}
      <Paper>
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Username</TableCell>
                <TableCell>Full Name</TableCell>
                <TableCell>Email</TableCell>
                <TableCell>SeaTalk ID</TableCell>
                <TableCell>Role</TableCell>
                <TableCell align="center">Status</TableCell>
                <TableCell>Last Login</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                    <CircularProgress size={32} />
                  </TableCell>
                </TableRow>
              ) : users.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                    No users found
                  </TableCell>
                </TableRow>
              ) : (
                users.map((user) => (
                  <TableRow key={user.id} hover>
                    <TableCell>
                      <Typography fontWeight="medium">{user.username}</Typography>
                    </TableCell>
                    <TableCell>{user.full_name || '-'}</TableCell>
                    <TableCell>{user.email || '-'}</TableCell>
                    <TableCell>
                      {user.seatalk_id ? (
                        <Tooltip title="Linked via SeaTalk">
                          <Chip
                            size="small"
                            label={user.seatalk_id}
                            variant="outlined"
                            icon={<CheckCircle />}
                          />
                        </Tooltip>
                      ) : (
                        <Typography variant="body2" color="text.secondary">-</Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={getRoleLabel(user.role)}
                        color={getRoleColor(user.role)}
                      />
                    </TableCell>
                    <TableCell align="center">
                      <Tooltip title={user.is_active ? 'Active - Click to deactivate' : 'Inactive - Click to activate'}>
                        <IconButton
                          size="small"
                          onClick={() => handleToggleActive(user)}
                          color={user.is_active ? 'success' : 'default'}
                        >
                          {user.is_active ? <CheckCircle /> : <Cancel />}
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      {user.last_login
                        ? new Date(user.last_login).toLocaleString()
                        : 'Never'}
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title="Edit User">
                        <IconButton
                          size="small"
                          onClick={() => handleOpenEditDialog(user)}
                        >
                          <Edit fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Change Password">
                        <IconButton
                          size="small"
                          onClick={() => handleOpenPasswordDialog(user)}
                        >
                          <Lock fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete User">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => handleOpenDeleteDialog(user)}
                        >
                          <Delete fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{selectedUser ? 'Edit User' : 'Create New User'}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField
              label="Username"
              value={formData.username}
              onChange={(e) => setFormData({ ...formData, username: e.target.value })}
              disabled={!!selectedUser}
              required
              fullWidth
              helperText={selectedUser ? 'Username cannot be changed' : 'Letters, numbers and underscores only'}
            />
            <TextField
              label="Full Name"
              value={formData.full_name}
              onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
              fullWidth
            />
            <TextField
              label="Email"
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              fullWidth
            />
            {!selectedUser && (
              <TextField
                label="Password"
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                required
                fullWidth
                helperText="Minimum 8 characters"
              />
            )}
            <FormControl fullWidth>
              <InputLabel>Role</InputLabel>
              <Select
                value={formData.role}
                label="Role"
                onChange={(e) => setFormData({ ...formData, role: e.target.value as UserRole })}
              >
                <MenuItem value="ADMIN">Administrator</MenuItem>
                <MenuItem value="WAREHOUSE_OP">Warehouse Operator</MenuItem>
                <MenuItem value="SALES_REP">Sales Representative</MenuItem>
                <MenuItem value="ACCOUNTANT">Accountant</MenuItem>
              </Select>
            </FormControl>
            <FormControlLabel
              control={
                <Switch
                  checked={formData.is_active}
                  onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                />
              }
              label="Active"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleSubmit}
            variant="contained"
            disabled={
              createUserMutation.isPending ||
              updateUserMutation.isPending ||
              !formData.username ||
              (!selectedUser && !formData.password)
            }
          >
            {createUserMutation.isPending || updateUserMutation.isPending
              ? 'Saving...'
              : selectedUser
              ? 'Save Changes'
              : 'Create User'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Change Password Dialog */}
      <Dialog open={passwordDialogOpen} onClose={() => setPasswordDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Change Password for {selectedUser?.username}</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 1 }}>
            <TextField
              label="New Password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              fullWidth
              required
              helperText="Minimum 8 characters"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPasswordDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleChangePassword}
            variant="contained"
            disabled={changePasswordMutation.isPending || newPassword.length < 8}
          >
            {changePasswordMutation.isPending ? 'Saving...' : 'Change Password'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>Delete User</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mt: 1 }}>
            Are you sure you want to delete user <strong>{selectedUser?.username}</strong>? This action cannot be undone.
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleDeleteUser}
            variant="contained"
            color="error"
            disabled={deleteUserMutation.isPending}
          >
            {deleteUserMutation.isPending ? 'Deleting...' : 'Delete User'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Notification Snackbar */}
      <Snackbar
        open={notification.open}
        autoHideDuration={4000}
        onClose={() => setNotification({ ...notification, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          onClose={() => setNotification({ ...notification, open: false })}
          severity={notification.severity}
          sx={{ width: '100%' }}
        >
          {notification.message}
        </Alert>
      </Snackbar>
    </Box>
  )
}
