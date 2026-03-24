import { useState } from 'react'
import { Box, TextField, Typography, Paper } from '@mui/material'
import { DataGrid, GridColDef } from '@mui/x-data-grid'
import { useQuery } from '@tanstack/react-query'
import axiosClient from '../api/axiosClient'
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

export default function StockLookup() {
  const [searchSku, setSearchSku] = useState('')
  const [queryKey, setQueryKey] = useState('')

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

  const rows = (data?.items || []).map((item: InventoryItem, index: number) => ({
    ...item,
    id: item.id || index,
  }))

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Stock Lookup
      </Typography>

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
    </Box>
  )
}
