import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import Login from './pages/Login'
import SeaTalkCallback from './pages/SeaTalkCallback'
import Dashboard from './pages/Dashboard'
import WarehouseOps from './pages/WarehouseOps'
import InventoryManagement from './pages/InventoryManagement'
import ProductListings from './pages/ProductListings'
import OrdersManagement from './pages/OrdersManagement'
import UserManagement from './pages/UserManagement'
import Layout from './components/common/Layout'
import RoleGuard from './components/guards/RoleGuard'

function App() {
  const { isAuthenticated } = useAuth()

  return (
    <>
      {/* --- TEMPORARY DEBUG BANNER --- */}
      <div style={{ 
        padding: '16px', 
        backgroundColor: '#ffeb3b', 
        color: '#000', 
        wordBreak: 'break-all',
        marginBottom: '20px',
        border: '2px solid red'
      }}>
        <strong>Full URL:</strong> {window.location.href} <br/><br/>
        <strong>Query Params:</strong> {window.location.search || "No query parameters found"}
      </div>
    
      <Routes>
        {/* Public Routes */}
        <Route
          path="/login"
          element={isAuthenticated ? <Navigate to="/" replace /> : <Login />}
        />
        <Route path="/auth/seatalk/callback" element={<SeaTalkCallback />} />

        {/* Protected Routes */}
        <Route
          element={
            <RoleGuard allowedRoles={['ADMIN', 'WAREHOUSE_OP', 'SALES_REP']}>
              <Layout />
            </RoleGuard>
          }
        >
          <Route path="/" element={<Dashboard />} />

          {/* Warehouse Routes */}
          <Route element={<RoleGuard allowedRoles={['ADMIN', 'WAREHOUSE_OP']} />}>
            <Route path="/warehouse/ops" element={<WarehouseOps />} />
          </Route>

          {/* Catalog Routes */}
          <Route element={<RoleGuard allowedRoles={['ADMIN', 'SALES_REP']} />}>
            <Route path="/catalog/inventory" element={<InventoryManagement />} />
            <Route path="/catalog/listings" element={<ProductListings />} />
          </Route>

          {/* Orders Routes */}
          <Route element={<RoleGuard allowedRoles={['ADMIN', 'SALES_REP', 'WAREHOUSE_OP']} />}>
            <Route path="/orders" element={<OrdersManagement />} />
          </Route>

          {/* Admin Routes */}
          <Route element={<RoleGuard allowedRoles={['ADMIN']} />}>
            <Route path="/admin/users" element={<UserManagement />} />
          </Route>
        </Route>

        {/* Catch all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}

export default App
