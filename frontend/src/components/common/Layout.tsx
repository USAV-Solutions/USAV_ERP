import { useEffect, useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  AppBar,
  Box,
  Collapse,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Divider,
  Avatar,
  Menu,
  MenuItem,
} from '@mui/material'
import {
  Menu as MenuIcon,
  Dashboard,
  Search,
  Inventory,
  Logout,
  Person,
  Storefront,
  People,
  ShoppingCart,
  LocalShipping,
  AccountBalance,
  Assessment,
  Transform,
  ExpandLess,
  ExpandMore,
} from '@mui/icons-material'
import { useAuth } from '../../hooks/useAuth'

const DRAWER_WIDTH = 240

interface NavItem {
  title: string
  path?: string
  icon: React.ReactNode
  roles: ('ADMIN' | 'WAREHOUSE_OP' | 'SALES_REP' | 'ACCOUNTANT')[]
  children?: NavItem[]
}

const navItems: NavItem[] = [
  { title: 'Dashboard', path: '/', icon: <Dashboard />, roles: ['ADMIN', 'WAREHOUSE_OP', 'SALES_REP'] },
  { title: 'Warehouse Operations', path: '/warehouse/ops', icon: <Search />, roles: ['ADMIN', 'WAREHOUSE_OP'] },
  { title: 'Inventory Management', path: '/catalog/inventory', icon: <Inventory />, roles: ['ADMIN', 'SALES_REP'] },
  { title: 'Product Listings', path: '/catalog/listings', icon: <Storefront />, roles: ['ADMIN', 'SALES_REP'] },
  { title: 'Orders', path: '/orders', icon: <ShoppingCart />, roles: ['ADMIN', 'SALES_REP', 'WAREHOUSE_OP'] },
  { title: 'Purchasing', path: '/purchasing', icon: <LocalShipping />, roles: ['ADMIN', 'SALES_REP', 'WAREHOUSE_OP'] },
  {
    title: 'Accounting',
    icon: <AccountBalance />,
    roles: ['ADMIN', 'ACCOUNTANT'],
    children: [
      { title: 'Reports', path: '/accounting/reports', icon: <Assessment />, roles: ['ADMIN', 'ACCOUNTANT'] },
      { title: 'Bank Conversion', path: '/accounting/bank-convert', icon: <Transform />, roles: ['ADMIN', 'ACCOUNTANT'] },
    ],
  },
  { title: 'User Management', path: '/admin/users', icon: <People />, roles: ['ADMIN'] },
]

export default function Layout() {
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [accountingOpen, setAccountingOpen] = useState(location.pathname.startsWith('/accounting/'))
  const { user, logout, hasRole } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (location.pathname.startsWith('/accounting/')) {
      setAccountingOpen(true)
    }
  }, [location.pathname])

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen)
  }

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }

  const handleMenuClose = () => {
    setAnchorEl(null)
  }

  const handleLogout = () => {
    handleMenuClose()
    logout()
    navigate('/login')
  }

  const filteredNavItems = navItems.filter((item) => hasRole(item.roles))

  const getCurrentTitle = () => {
    for (const item of filteredNavItems) {
      if (item.path && item.path === location.pathname) {
        return item.title
      }
      if (item.children) {
        const child = item.children.find((sub) => sub.path === location.pathname && hasRole(sub.roles))
        if (child) {
          return child.title
        }
      }
    }
    return 'USAV'
  }

  const drawer = (
    <Box>
      <Toolbar>
        <Typography variant="h6" noWrap>
          USAV Inventory
        </Typography>
      </Toolbar>
      <Divider />
      <List>
        {filteredNavItems.map((item, index) => {
          if (item.children) {
            const visibleChildren = item.children.filter((child) => hasRole(child.roles))
            if (visibleChildren.length === 0) {
              return null
            }

            return (
              <Box key={`${item.title}-${index}`}>
                <ListItem disablePadding>
                  <ListItemButton onClick={() => setAccountingOpen((open) => !open)}>
                    <ListItemIcon>{item.icon}</ListItemIcon>
                    <ListItemText primary={item.title} />
                    {accountingOpen ? <ExpandLess /> : <ExpandMore />}
                  </ListItemButton>
                </ListItem>
                <Collapse in={accountingOpen} timeout="auto" unmountOnExit>
                  <List component="div" disablePadding>
                    {visibleChildren.map((child) => (
                      <ListItem key={child.path} disablePadding>
                        <ListItemButton
                          selected={child.path ? location.pathname === child.path : false}
                          onClick={() => {
                            if (!child.path) {
                              return
                            }
                            navigate(child.path)
                            setMobileOpen(false)
                          }}
                          sx={{ pl: 4 }}
                        >
                          <ListItemIcon>{child.icon}</ListItemIcon>
                          <ListItemText primary={child.title} />
                        </ListItemButton>
                      </ListItem>
                    ))}
                  </List>
                </Collapse>
              </Box>
            )
          }

          return (
            <ListItem key={`${item.title}-${item.path ?? index}`} disablePadding>
              <ListItemButton
                selected={item.path ? location.pathname === item.path : false}
                disabled={!item.path}
                onClick={() => {
                  if (!item.path) {
                    return
                  }
                  navigate(item.path)
                  setMobileOpen(false)
                }}
              >
                <ListItemIcon>{item.icon}</ListItemIcon>
                <ListItemText primary={item.title} />
              </ListItemButton>
            </ListItem>
          )
        })}
      </List>
    </Box>
  )

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar
        position="fixed"
        sx={{
          width: { sm: `calc(100% - ${DRAWER_WIDTH}px)` },
          ml: { sm: `${DRAWER_WIDTH}px` },
        }}
      >
        <Toolbar>
          <IconButton
            color="inherit"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2, display: { sm: 'none' } }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" noWrap component="div" sx={{ flexGrow: 1 }}>
            {getCurrentTitle()}
          </Typography>
          <IconButton color="inherit" onClick={handleMenuOpen}>
            <Avatar sx={{ width: 32, height: 32, bgcolor: 'secondary.main' }}>
              {user?.username?.charAt(0).toUpperCase()}
            </Avatar>
          </IconButton>
          <Menu
            anchorEl={anchorEl}
            open={Boolean(anchorEl)}
            onClose={handleMenuClose}
            anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            transformOrigin={{ vertical: 'top', horizontal: 'right' }}
          >
            <MenuItem disabled>
              <ListItemIcon>
                <Person fontSize="small" />
              </ListItemIcon>
              {user?.username} ({user?.role})
            </MenuItem>
            <Divider />
            <MenuItem onClick={handleLogout}>
              <ListItemIcon>
                <Logout fontSize="small" />
              </ListItemIcon>
              Logout
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      <Box
        component="nav"
        sx={{ width: { sm: DRAWER_WIDTH }, flexShrink: { sm: 0 } }}
      >
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': { boxSizing: 'border-box', width: DRAWER_WIDTH },
          }}
        >
          {drawer}
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': { boxSizing: 'border-box', width: DRAWER_WIDTH },
          }}
          open
        >
          {drawer}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: { sm: `calc(100% - ${DRAWER_WIDTH}px)` },
          mt: '64px',
        }}
      >
        <Outlet />
      </Box>
    </Box>
  )
}
