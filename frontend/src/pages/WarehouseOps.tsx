import { useState } from 'react'
import {
  Box,
  TextField,
  Typography,
  Paper,
  Button,
  Alert,
  Snackbar,
} from '@mui/material'
import { Add, CheckCircle, Error as ErrorIcon } from '@mui/icons-material'
import { DataGrid, GridColDef } from '@mui/x-data-grid'
import { useQuery } from '@tanstack/react-query'
import axiosClient from '../api/axiosClient'
import CreateStockDialog from '../components/inventory/CreateStockDialog'
import { useAuth } from '../hooks/useAuth'
import { InventoryItem } from '../types/inventory'

const columns: GridColDef[] = [
  { field: 'serial_number', headerName: 'Serial Number', flex: 1 },
  { field: 'location_code', headerName: 'Location', width: 150 },
  {
    field: 'status',
    headerName: 'Status',
    width: 120,
    renderCell: (params) => {
      const colors: Record<string, string> = {
        IN_STOCK: '#4caf50',
        SOLD: '#f44336',
        RESERVED: '#ff9800',
        DAMAGED: '#9e9e9e',
      }
      return (
        <Box
          sx={{
            px: 1,
            py: 0.5,
            borderRadius: 1,
            bgcolor: colors[params.value] || '#9e9e9e',
            color: 'white',
            fontSize: '0.75rem',
          }}
        >
          {params.value}
        </Box>
      )
    },
  },
  { field: 'received_at', headerName: 'Received', width: 180 },
]

export default function WarehouseOps() {
  const [searchSku, setSearchSku] = useState('')
  const [queryKey, setQueryKey] = useState('')
  const [createStockDialogOpen, setCreateStockDialogOpen] = useState(false)
  const [notification, setNotification] = useState<{
    open: boolean
    message: string
    severity: 'success' | 'error'
  }>({ open: false, message: '', severity: 'success' })
  
  const { hasRole } = useAuth()

  const { data, isLoading, error } = useQuery({
    queryKey: ['inventory-lookup', queryKey],
    queryFn: async () => {
      if (!queryKey) return { items: [] }
      const response = await axiosClient.get(`/inventory/audit/${queryKey}`)
      return response.data
    },
    enabled: !!queryKey,
  })

  const handleSearch = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && searchSku.trim()) {
      setQueryKey(searchSku.trim())
    }
  }

  const showNotification = (message: string, severity: 'success' | 'error') => {
    setNotification({ open: true, message, severity })
  }

  const rows = (data?.items || []).map((item: InventoryItem, index: number) => ({
    ...item,
    id: item.id || index,
  }))

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">Warehouse Operations</Typography>
        {hasRole(['ADMIN', 'WAREHOUSE_OP']) && (
          <Button
            variant="contained"
            startIcon={<Add />}
            onClick={() => setCreateStockDialogOpen(true)}
          >
            Create Stock
          </Button>
        )}
      </Box>

      {/* Stock Lookup Search */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <TextField
          fullWidth
          label="Search by SKU"
          placeholder="Enter SKU and press Enter"
          value={searchSku}
          onChange={(e) => setSearchSku(e.target.value)}
          onKeyDown={handleSearch}
          autoFocus
        />
      </Paper>

      {error && (
        <Typography color="error" sx={{ mb: 2 }}>
          Error loading inventory data
        </Typography>
      )}

      {/* Stock Results Table */}
      <Paper sx={{ height: 500 }}>
        <DataGrid
          rows={rows}
          columns={columns}
          loading={isLoading}
          pageSizeOptions={[10, 25, 50]}
          initialState={{
            pagination: { paginationModel: { pageSize: 10 } },
          }}
          disableRowSelectionOnClick
        />
      </Paper>

      {/* Notification Snackbar */}
      <Snackbar
        open={notification.open}
        autoHideDuration={4000}
        onClose={() => setNotification((prev) => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert
          severity={notification.severity}
          icon={notification.severity === 'success' ? <CheckCircle /> : <ErrorIcon />}
          sx={{ fontSize: '1.2rem' }}
        >
          {notification.message}
        </Alert>
      </Snackbar>

      {/* Create Stock Dialog */}
      <CreateStockDialog
        open={createStockDialogOpen}
        onClose={() => setCreateStockDialogOpen(false)}
        onSuccess={(item) => {
          showNotification(`Stock item created: ${item.serial_number || `ID ${item.id}`}`, 'success')
        }}
      />
    </Box>
  )
}
