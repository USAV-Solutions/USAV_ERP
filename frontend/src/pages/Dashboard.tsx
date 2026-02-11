import { Box, Grid, Card, CardContent, Typography, Paper, Chip, Divider } from '@mui/material'
import {
  Search,
  Inventory,
  Storefront,
  People,
  TrendingUp,
} from '@mui/icons-material'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

interface QuickAction {
  title: string
  description: string
  path: string
  icon: React.ReactNode
  color: string
  roles: ('ADMIN' | 'WAREHOUSE_OP' | 'SALES_REP')[]
}

const quickActions: QuickAction[] = [
  {
    title: 'Warehouse Operations',
    description: 'Search stock, create new stock items',
    path: '/warehouse/ops',
    icon: <Search sx={{ fontSize: 40 }} />,
    color: '#1976d2',
    roles: ['ADMIN', 'WAREHOUSE_OP'],
  },
  {
    title: 'Inventory Management',
    description: 'Manage products, variants and stock',
    path: '/catalog/inventory',
    icon: <Inventory sx={{ fontSize: 40 }} />,
    color: '#ed6c02',
    roles: ['ADMIN', 'SALES_REP'],
  },
  {
    title: 'Product Listings',
    description: 'View and manage marketplace listings',
    path: '/catalog/listings',
    icon: <Storefront sx={{ fontSize: 40 }} />,
    color: '#9c27b0',
    roles: ['ADMIN', 'SALES_REP'],
  },
  {
    title: 'User Management',
    description: 'Manage users, roles and permissions',
    path: '/admin/users',
    icon: <People sx={{ fontSize: 40 }} />,
    color: '#d32f2f',
    roles: ['ADMIN'],
  },
]

export default function Dashboard() {
  const navigate = useNavigate()
  const { user, hasRole } = useAuth()

  const filteredActions = quickActions.filter((action) =>
    hasRole(action.roles)
  )

  const getRoleColor = (role: string): 'primary' | 'secondary' | 'success' | 'warning' | 'error' => {
    switch (role) {
      case 'ADMIN': return 'error'
      case 'WAREHOUSE_OP': return 'primary'
      case 'SALES_REP': return 'success'
      default: return 'secondary'
    }
  }

  const getRoleLabel = (role: string): string => {
    switch (role) {
      case 'ADMIN': return 'Administrator'
      case 'WAREHOUSE_OP': return 'Warehouse Operator'
      case 'SALES_REP': return 'Sales Representative'
      default: return role
    }
  }

  return (
    <Box>
      {/* Welcome Section */}
      <Paper 
        sx={{ 
          p: 3, 
          mb: 4, 
          background: 'linear-gradient(135deg, #1976d2 0%, #1565c0 100%)',
          color: 'white',
          borderRadius: 2,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2 }}>
          <Box>
            <Typography variant="h4" fontWeight="bold" gutterBottom>
              Welcome back, {user?.username}!
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Chip 
                label={getRoleLabel(user?.role || '')} 
                color={getRoleColor(user?.role || '')}
                size="small"
                sx={{ fontWeight: 'medium' }}
              />
            </Box>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <TrendingUp sx={{ fontSize: 32 }} />
            <Typography variant="body2" sx={{ opacity: 0.9 }}>
              USAV Inventory System
            </Typography>
          </Box>
        </Box>
      </Paper>

      {/* Quick Actions Section */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="h5" fontWeight="medium" gutterBottom>
          Quick Actions
        </Typography>
        <Divider sx={{ mb: 3 }} />
      </Box>
      
      <Grid container spacing={3}>
        {filteredActions.map((action) => (
          <Grid item xs={12} sm={6} md={4} lg={3} key={action.path}>
            <Card
              sx={{
                height: '100%',
                cursor: 'pointer',
                transition: 'all 0.2s ease-in-out',
                border: '1px solid',
                borderColor: 'divider',
                '&:hover': {
                  transform: 'translateY(-6px)',
                  boxShadow: 6,
                  borderColor: action.color,
                },
              }}
              onClick={() => navigate(action.path)}
            >
              <CardContent
                sx={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  textAlign: 'center',
                  p: 3,
                  height: '100%',
                }}
              >
                <Box 
                  sx={{ 
                    color: 'white', 
                    bgcolor: action.color, 
                    borderRadius: '50%',
                    p: 2,
                    mb: 2,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {action.icon}
                </Box>
                <Typography variant="h6" fontWeight="medium" gutterBottom>
                  {action.title}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {action.description}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  )
}
