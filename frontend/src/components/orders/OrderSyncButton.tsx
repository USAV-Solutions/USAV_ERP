/**
 * OrderSyncButton – triggers the Safe Sync for one or all platforms.
 *
 * Displays a dialog where the user picks a platform (or "all"), fires
 * the POST /orders/sync request, and shows a result summary snackbar.
 */
import { useState } from 'react'
import {
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  CircularProgress,
  Box,
  Typography,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
} from '@mui/material'
import {
  Sync,
  CheckCircle,
  Error as ErrorIcon,
} from '@mui/icons-material'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { syncOrders } from '../../api/orders'
import type { SyncResponse } from '../../types/orders'

const PLATFORM_OPTIONS = [
  { value: '', label: 'All Configured Platforms' },
  { value: 'ECWID', label: 'Ecwid' },
  { value: 'EBAY_MEKONG', label: 'eBay Mekong' },
  { value: 'EBAY_USAV', label: 'eBay USAV' },
  { value: 'EBAY_DRAGON', label: 'eBay Dragon' },
  { value: 'AMAZON', label: 'Amazon' },
] as const

export default function OrderSyncButton() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [platform, setPlatform] = useState('')
  const [results, setResults] = useState<SyncResponse[] | null>(null)

  const mutation = useMutation({
    mutationFn: () => syncOrders(platform ? { platform } : {}),
    onSuccess: (data: SyncResponse[]) => {
      setResults(data)
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
    },
  })

  const handleClose = () => {
    setOpen(false)
    setResults(null)
    mutation.reset()
  }

  return (
    <>
      <Button
        variant="contained"
        startIcon={<Sync />}
        onClick={() => setOpen(true)}
      >
        Sync Orders
      </Button>

      <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
        <DialogTitle>Sync Orders from Platform</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {/* Platform selector */}
            <FormControl fullWidth>
              <InputLabel>Platform</InputLabel>
              <Select
                value={platform}
                onChange={(e: { target: { value: string } }) => setPlatform(e.target.value)}
                label="Platform"
                disabled={mutation.isPending}
              >
                {PLATFORM_OPTIONS.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <Alert severity="info" variant="outlined">
              Sync fetches new orders since the last successful sync for the
              selected platform(s). Duplicate orders are automatically skipped.
            </Alert>

            {/* Error */}
            {mutation.isError && (
              <Alert severity="error">
                {(mutation.error as Error)?.message || 'Sync request failed.'}
              </Alert>
            )}

            {/* Results */}
            {results && (
              <Box>
                <Typography variant="subtitle2" gutterBottom>
                  Sync Results
                </Typography>
                <List dense disablePadding>
                  {results.map((r: SyncResponse) => (
                    <ListItem key={r.platform} disableGutters>
                      <ListItemIcon sx={{ minWidth: 32 }}>
                        {r.success ? (
                          <CheckCircle color="success" fontSize="small" />
                        ) : (
                          <ErrorIcon color="error" fontSize="small" />
                        )}
                      </ListItemIcon>
                      <ListItemText
                        primary={r.platform}
                        secondary={
                          r.success
                            ? `${r.new_orders} new orders, ${r.auto_matched} auto-matched, ${r.skipped_duplicates} skipped`
                            : r.errors.join('; ')
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              </Box>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>
            {results ? 'Close' : 'Cancel'}
          </Button>
          {!results && (
            <Button
              variant="contained"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              startIcon={
                mutation.isPending ? <CircularProgress size={18} /> : <Sync />
              }
            >
              {mutation.isPending ? 'Syncing...' : 'Start Sync'}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </>
  )
}
