/**
 * AdminDateRangeSync – Admin-only button for syncing orders within a custom
 * date range. Allows choosing a start and end time to fetch historical orders
 * from platform APIs.  Duplicate orders are still safely skipped.
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
  TextField,
} from '@mui/material'
import {
  DateRange,
  CheckCircle,
  Error as ErrorIcon,
} from '@mui/icons-material'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { syncOrdersRange } from '../../api/orders'
import type { SyncResponse } from '../../types/orders'

const PLATFORM_OPTIONS = [
  { value: '', label: 'All Configured Platforms' },
  { value: 'ECWID', label: 'Ecwid' },
  { value: 'EBAY_MEKONG', label: 'eBay Mekong' },
  { value: 'EBAY_USAV', label: 'eBay USAV' },
  { value: 'EBAY_DRAGON', label: 'eBay Dragon' },
  { value: 'AMAZON', label: 'Amazon' },
] as const

export default function AdminDateRangeSync() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [platform, setPlatform] = useState('')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [results, setResults] = useState<SyncResponse[] | null>(null)

  const mutation = useMutation({
    mutationFn: () =>
      syncOrdersRange({
        platform: platform || undefined,
        since: new Date(since).toISOString(),
        until: new Date(until).toISOString(),
      }),
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

  const isValid = since && until && new Date(since) < new Date(until)

  return (
    <>
      <Button
        variant="outlined"
        startIcon={<DateRange />}
        onClick={() => setOpen(true)}
        size="small"
      >
        Range Sync
      </Button>

      <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
        <DialogTitle>Admin: Sync Orders by Date Range</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {/* Platform selector */}
            <FormControl fullWidth>
              <InputLabel>Platform</InputLabel>
              <Select
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
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

            {/* Date range pickers */}
            <TextField
              label="Start Date & Time"
              type="datetime-local"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              disabled={mutation.isPending}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="End Date & Time"
              type="datetime-local"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              disabled={mutation.isPending}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />

            <Alert severity="warning" variant="outlined">
              Admin-only: fetches orders within the selected date range.
              This bypasses the normal sync lock. Duplicate orders are
              automatically skipped.
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
              disabled={!isValid || mutation.isPending}
              startIcon={
                mutation.isPending ? <CircularProgress size={18} /> : <DateRange />
              }
            >
              {mutation.isPending ? 'Syncing...' : 'Start Range Sync'}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </>
  )
}
