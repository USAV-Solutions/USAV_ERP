import React, { useState, useEffect, useRef } from 'react'
import {
  Box,
  TextField,
  Typography,
  Paper,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Chip,
  Grid,
  CircularProgress,
} from '@mui/material'
import {
  ExpandMore,
  CheckCircle,
  Error as ErrorIcon,
  QrCodeScanner,
  VolumeUp,
  HelpOutline,
  CloudQueue,
  CloudDone,
  CloudOff,
  Sync,
} from '@mui/icons-material'
import { scanBarcode, BarcodeScanResponse } from '../api/orders'
import { useAuth } from '../hooks/useAuth'

interface ScanItem {
  id: string
  trackingNumber: string
  scannedAt: string
  syncStatus: 'pending' | 'syncing' | 'synced' | 'network_error'
  matched?: boolean
  message: string
  orderId?: number
  platform?: string
}

export default function WarehouseScan() {
  const auth = useAuth()
  const [barcode, setBarcode] = useState('')
  const [lastScanId, setLastScanId] = useState<string | null>(null)
  
  // Initialize scan history queue from browser's localStorage
  const [history, setHistory] = useState<ScanItem[]>(() => {
    try {
      const saved = localStorage.getItem('usav_scan_queue')
      return saved ? JSON.parse(saved) : []
    } catch (e) {
      console.error('Failed to parse scan queue from localStorage', e)
      return []
    }
  })

  const inputRef = useRef<HTMLInputElement>(null)

  // Save to localStorage on queue changes
  useEffect(() => {
    localStorage.setItem('usav_scan_queue', JSON.stringify(history))
  }, [history])

  // Keep input focused at all times
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus()
    }
  }, [])

  const handleBlur = () => {
    setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.focus()
      }
    }, 150)
  }

  const handleContainerClick = () => {
    if (inputRef.current) {
      inputRef.current.focus()
    }
  }

  // Audio Tone Generator using Web Audio API
  const playBeep = (type: 'success' | 'error' | 'captured') => {
    try {
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
      if (!AudioContextClass) return
      const ctx = new AudioContextClass()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)

      if (type === 'success') {
        osc.type = 'sine'
        osc.frequency.setValueAtTime(1000, ctx.currentTime)
        gain.gain.setValueAtTime(0.15, ctx.currentTime)
        osc.start()
        osc.stop(ctx.currentTime + 0.08)
      } else if (type === 'error') {
        osc.type = 'sawtooth'
        osc.frequency.setValueAtTime(140, ctx.currentTime)
        gain.gain.setValueAtTime(0.2, ctx.currentTime)
        osc.start()
        osc.stop(ctx.currentTime + 0.3)
      } else if (type === 'captured') {
        // Simple click tone when scanner gun captures the barcode locally
        osc.type = 'sine'
        osc.frequency.setValueAtTime(600, ctx.currentTime)
        gain.gain.setValueAtTime(0.08, ctx.currentTime)
        osc.start()
        osc.stop(ctx.currentTime + 0.03)
      }
    } catch (e) {
      console.warn('Audio feedback blocked by browser:', e)
    }
  }

  // Background sync worker loop
  useEffect(() => {
    let active = true
    
    const runSync = async () => {
      // Find the first unsynced item (starting from oldest scanned to keep chronological updates)
      const pendingItem = [...history]
        .reverse()
        .find((item) => item.syncStatus === 'pending' || item.syncStatus === 'network_error')

      if (!pendingItem) return

      // Mark the item as syncing locally
      setHistory((prev) =>
        prev.map((item) =>
          item.id === pendingItem.id ? { ...item, syncStatus: 'syncing' } : item
        )
      )

      try {
        const response: BarcodeScanResponse = await scanBarcode({
          tracking_number: pendingItem.trackingNumber,
          scanned_by: auth.user?.username || 'US Warehouse Terminal',
        })

        if (!active) return

        // Update with successful API response
        setHistory((prev) =>
          prev.map((item) =>
            item.id === pendingItem.id
              ? {
                  ...item,
                  syncStatus: 'synced',
                  matched: response.matched,
                  message: response.message,
                  orderId: response.order_id,
                  platform: response.platform,
                }
              : item
          )
        )

        // If this synced item is the most recent scanned item, play feedback immediately
        if (pendingItem.id === lastScanId) {
          playBeep(response.matched ? 'success' : 'error')
        }
      } catch (err: any) {
        if (!active) return

        // If it's a network offline error, mark status as network_error
        const isNetworkError = !err.response
        const errMsg = err.response?.data?.detail || 'No response from Vietnam server'

        setHistory((prev) =>
          prev.map((item) =>
            item.id === pendingItem.id
              ? {
                  ...item,
                  syncStatus: isNetworkError ? 'network_error' : 'synced',
                  matched: false,
                  message: isNetworkError ? 'Offline: VM in Vietnam unreachable. Retrying...' : errMsg,
                }
              : item
          )
        )

        if (pendingItem.id === lastScanId) {
          playBeep('error')
        }
      }
    }

    // Run every 2 seconds if there are items in the queue
    const timer = setInterval(() => {
      runSync()
    }, 2000)

    return () => {
      active = false
      clearInterval(timer)
    }
  }, [history, lastScanId, auth.user])

  const handleScanSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const cleaned = barcode.trim()
    if (!cleaned) return

    // Play local capture tone instantly so the operator knows the code was registered
    playBeep('captured')

    const newId = Math.random().toString(36).substr(2, 9)
    const newEntry: ScanItem = {
      id: newId,
      trackingNumber: cleaned,
      scannedAt: new Date().toLocaleTimeString(),
      syncStatus: 'pending',
      message: 'Pending sync to Vietnam server...',
    }

    setLastScanId(newId)
    setHistory((prev) => [newEntry, ...prev])
    setBarcode('')

    // Refocus input
    if (inputRef.current) {
      inputRef.current.focus()
    }
  }

  // Clear history function
  const handleClearHistory = () => {
    if (window.confirm('Are you sure you want to clear your local scan history?')) {
      setHistory([])
      setLastScanId(null)
    }
  }

  // Manual retry for a specific item
  const handleManualRetry = (id: string) => {
    setHistory((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, syncStatus: 'pending', message: 'Retrying sync...' } : item
      )
    )
  }

  // Find details of the active scan
  const activeScanItem = history.find((item) => item.id === lastScanId)

  // Status metrics
  const pendingCount = history.filter((item) => item.syncStatus === 'pending' || item.syncStatus === 'syncing').length
  const offlineCount = history.filter((item) => item.syncStatus === 'network_error').length
  const syncedCount = history.filter((item) => item.syncStatus === 'synced').length

  return (
    <Box onClick={handleContainerClick} sx={{ minHeight: '80vh', cursor: 'default', pb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" sx={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <QrCodeScanner color="primary" fontSize="large" /> Barcode Ingestion Scanner
        </Typography>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          {pendingCount > 0 && (
            <Chip
              icon={<Sync className="spin-animation" />}
              label={`Syncing ${pendingCount} scan(s)...`}
              color="info"
              variant="outlined"
            />
          )}
          {offlineCount > 0 && (
            <Chip
              icon={<CloudOff />}
              label={`${offlineCount} Offline Pending`}
              color="warning"
            />
          )}
          {syncedCount > 0 && pendingCount === 0 && offlineCount === 0 && (
            <Chip
              icon={<CloudDone />}
              label="All synced to Vietnam"
              color="success"
              variant="outlined"
            />
          )}
        </Box>
      </Box>

      <Grid container spacing={3}>
        {/* Left Control Column */}
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 3, mb: 3, textAlign: 'center', border: '1px solid rgba(0, 0, 0, 0.12)' }}>
            <Typography variant="h6" gutterBottom sx={{ color: 'text.secondary', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 1 }}>
              <CloudQueue /> US-Vietnam Scan Assistant
            </Typography>
            
            <form onSubmit={handleScanSubmit}>
              <TextField
                inputRef={inputRef}
                variant="outlined"
                fullWidth
                placeholder="Scan tracking barcode here..."
                value={barcode}
                onChange={(e) => setBarcode(e.target.value)}
                onBlur={handleBlur}
                autoComplete="off"
                inputProps={{
                  style: {
                    textAlign: 'center',
                    fontSize: '1.25rem',
                    letterSpacing: '0.1rem',
                  },
                }}
                sx={{ mb: 2 }}
              />
              <Button
                type="submit"
                variant="contained"
                fullWidth
                disabled={!barcode.trim()}
                sx={{ py: 1.2, fontWeight: 'bold' }}
              >
                Scan / Submit
              </Button>
            </form>

            <Box sx={{ mt: 2, display: 'flex', justifyContent: 'space-between', gap: 1 }}>
              <Button size="small" variant="outlined" color="error" onClick={handleClearHistory} disabled={history.length === 0}>
                Clear Cache
              </Button>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button size="small" startIcon={<VolumeUp />} onClick={() => playBeep('success')}>
                  Beep
                </Button>
                <Button size="small" startIcon={<VolumeUp />} onClick={() => playBeep('error')} color="error">
                  Buzz
                </Button>
              </Box>
            </Box>
          </Paper>

          {/* Setup Guide */}
          <Accordion sx={{ border: '1px solid rgba(0, 0, 0, 0.12)', boxShadow: 'none' }}>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Typography sx={{ display: 'flex', alignItems: 'center', gap: 1, fontWeight: '500' }}>
                <HelpOutline color="action" fontSize="small" /> US-Vietnam Connectivity FAQ
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2" color="text.secondary" paragraph>
                <strong>Q: How does this handle slow connection to Vietnam?</strong>
                <br />
                The page records your barcode scans instantly in local browser storage (`localStorage`). Scans are then sent to the Vietnam ERP server in the background. You do not need to wait for a success screen before scanning the next package.
              </Typography>
              <Typography variant="body2" color="text.secondary" paragraph>
                <strong>Q: What happens if Vietnam VM drops offline?</strong>
                <br />
                The barcode will list as <strong>"Offline: VM unreachable"</strong>. It is saved safely on your computer. The system automatically retries syncing every 2 seconds when network recovers.
              </Typography>
            </AccordionDetails>
          </Accordion>
        </Grid>

        {/* Right Status / History Column */}
        <Grid item xs={12} md={7}>
          {/* Active Status Display */}
          <Paper
            sx={{
              p: 4,
              mb: 3,
              minHeight: 180,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              alignItems: 'center',
              textAlign: 'center',
              transition: 'all 0.3s ease',
              bgcolor:
                !activeScanItem
                  ? 'background.paper'
                  : activeScanItem.syncStatus === 'pending' || activeScanItem.syncStatus === 'syncing'
                  ? 'info.light'
                  : activeScanItem.syncStatus === 'network_error'
                  ? 'warning.light'
                  : activeScanItem.matched
                  ? 'success.light'
                  : 'error.light',
              color:
                !activeScanItem
                  ? 'text.primary'
                  : activeScanItem.syncStatus === 'pending' || activeScanItem.syncStatus === 'syncing'
                  ? 'info.contrastText'
                  : activeScanItem.syncStatus === 'network_error'
                  ? 'warning.contrastText'
                  : activeScanItem.matched
                  ? 'success.contrastText'
                  : 'error.contrastText',
              border: '1px solid rgba(0, 0, 0, 0.12)',
            }}
          >
            {!activeScanItem ? (
              <>
                <QrCodeScanner sx={{ fontSize: 60, mb: 1, opacity: 0.4 }} />
                <Typography variant="h5" sx={{ fontWeight: 500 }}>
                  Ready to Scan Barcode
                </Typography>
                <Typography variant="body2" sx={{ opacity: 0.7, mt: 1 }}>
                  Automatic local backup active. Point scanner and scan.
                </Typography>
              </>
            ) : (
              <>
                {activeScanItem.syncStatus === 'syncing' || activeScanItem.syncStatus === 'pending' ? (
                  <>
                    <CircularProgress color="inherit" size={50} sx={{ mb: 2 }} />
                    <Typography variant="h5" sx={{ fontWeight: 700 }}>
                      SYNCING TO VIETNAM...
                    </Typography>
                    <Typography variant="h6" sx={{ mt: 1, wordBreak: 'break-all' }}>
                      {activeScanItem.trackingNumber}
                    </Typography>
                  </>
                ) : activeScanItem.syncStatus === 'network_error' ? (
                  <>
                    <CloudOff sx={{ fontSize: 60, mb: 1 }} />
                    <Typography variant="h4" sx={{ fontWeight: 700, mb: 1 }}>
                      OFFLINE QUEUED
                    </Typography>
                    <Typography variant="h6" sx={{ wordBreak: 'break-all', fontWeight: 'bold' }}>
                      {activeScanItem.trackingNumber}
                    </Typography>
                    <Typography variant="body1" sx={{ mt: 1 }}>
                      {activeScanItem.message}
                    </Typography>
                  </>
                ) : activeScanItem.matched ? (
                  <>
                    <CheckCircle sx={{ fontSize: 60, mb: 1 }} />
                    <Typography variant="h4" sx={{ fontWeight: 700, mb: 1 }}>
                      SCAN MATCHED
                    </Typography>
                    <Typography variant="h6" sx={{ wordBreak: 'break-all', fontWeight: 'bold' }}>
                      {activeScanItem.trackingNumber}
                    </Typography>
                    <Typography variant="body1" sx={{ mt: 1, opacity: 0.9 }}>
                      {activeScanItem.message}
                    </Typography>
                    {activeScanItem.platform && (
                      <Chip
                        label={activeScanItem.platform.toUpperCase()}
                        color="primary"
                        sx={{ mt: 1.5, fontWeight: 'bold' }}
                      />
                    )}
                  </>
                ) : (
                  <>
                    <ErrorIcon sx={{ fontSize: 60, mb: 1 }} />
                    <Typography variant="h4" sx={{ fontWeight: 700, mb: 1 }}>
                      MATCH FAILED
                    </Typography>
                    <Typography variant="h6" sx={{ wordBreak: 'break-all', fontWeight: 'bold' }}>
                      {activeScanItem.trackingNumber}
                    </Typography>
                    <Typography variant="body1" sx={{ mt: 1, opacity: 0.9 }}>
                      {activeScanItem.message}
                    </Typography>
                  </>
                )}
              </>
            )}
          </Paper>

          {/* Session Scan History List */}
          <Paper sx={{ p: 2, border: '1px solid rgba(0, 0, 0, 0.12)' }}>
            <Typography variant="h6" gutterBottom sx={{ px: 1, fontWeight: 'bold' }}>
              Local Scan History ({history.length} scans)
            </Typography>
            <TableContainer sx={{ maxHeight: 350 }}>
              <Table stickyHeader size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Time</TableCell>
                    <TableCell>Tracking Number</TableCell>
                    <TableCell>Sync Status</TableCell>
                    <TableCell>Match Message</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {history.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                        No scans recorded in this session.
                      </TableCell>
                    </TableRow>
                  ) : (
                    history.map((entry) => (
                      <TableRow key={entry.id} hover>
                        <TableCell sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}>
                          {entry.scannedAt}
                        </TableCell>
                        <TableCell sx={{ fontWeight: 'bold', wordBreak: 'break-all' }}>
                          {entry.trackingNumber}
                        </TableCell>
                        <TableCell>
                          {entry.syncStatus === 'synced' ? (
                            <Chip
                              size="small"
                              label={entry.matched ? 'MATCHED' : 'UNMATCHED'}
                              color={entry.matched ? 'success' : 'error'}
                              sx={{ fontWeight: 'bold', borderRadius: 1 }}
                            />
                          ) : entry.syncStatus === 'syncing' ? (
                            <Chip
                              size="small"
                              label="SYNCING"
                              color="info"
                              sx={{ fontWeight: 'bold', borderRadius: 1 }}
                            />
                          ) : (
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Chip
                                size="small"
                                label="OFFLINE"
                                color="warning"
                                sx={{ fontWeight: 'bold', borderRadius: 1 }}
                              />
                              <Button
                                size="small"
                                sx={{ minWidth: 0, p: 0.5 }}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleManualRetry(entry.id)
                                }}
                              >
                                Retry
                              </Button>
                            </Box>
                          )}
                        </TableCell>
                        <TableCell
                          sx={{
                            color:
                              entry.syncStatus === 'synced'
                                ? entry.matched
                                  ? 'text.primary'
                                  : 'error.main'
                                : 'text.secondary',
                          }}
                        >
                          {entry.message}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>
      </Grid>
      
      {/* Dynamic Spin Styles for syncing spinner */}
      <style>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        .spin-animation {
          animation: spin 1.5s linear infinite;
        }
      `}</style>
    </Box>
  )
}
