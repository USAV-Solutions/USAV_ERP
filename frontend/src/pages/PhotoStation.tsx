import React, { useState, useEffect, useRef } from 'react'
import {
  Box,
  TextField,
  Typography,
  Paper,
  Button,
  Grid,
  Chip,
  Alert,
  CircularProgress,
  Card,
  CardContent,
  IconButton,
} from '@mui/material'
import {
  CameraAlt,
  CheckCircle,
  Error as ErrorIcon,
  Cameraswitch,
  QrCodeScanner,
  VolumeUp,
  Refresh,
  Image,
} from '@mui/icons-material'
import axiosClient from '../api/axiosClient'
import { useAuth } from '../hooks/useAuth'

interface PendingOrder {
  id: number
  external_order_id: string
  external_order_number?: string
  platform: string
  ordered_at?: string
  total_amount: number
  tracking_number?: string
}

export default function PhotoStation() {
  const { user } = useAuth()
  const [orderNumber, setOrderNumber] = useState('')
  const [trackingNumber, setTrackingNumber] = useState('')
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([])
  const [isLoadingPending, setIsLoadingPending] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  
  // Camera State
  const videoRef = useRef<HTMLVideoElement>(null)
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment')
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null)
  const [slipPhotoData, setSlipPhotoData] = useState<string | null>(null)
  const [boxPhotoData, setBoxPhotoData] = useState<string | null>(null)
  
  // Feedback Status
  const [statusState, setStatusState] = useState<'IDLE' | 'VERIFIED' | 'ERROR_MISSING_TRACKING' | 'ERROR_NOT_FOUND'>('IDLE')
  const [statusMessage, setStatusMessage] = useState('')

  const inputRef = useRef<HTMLInputElement>(null)

  // Audio tone generator
  const playSound = (type: 'success' | 'error') => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
      if (!AudioCtx) return
      const ctx = new AudioCtx()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)

      if (type === 'success') {
        osc.type = 'sine'
        osc.frequency.setValueAtTime(880, ctx.currentTime) // High A note
        gain.gain.setValueAtTime(0.2, ctx.currentTime)
        osc.start()
        osc.stop(ctx.currentTime + 0.12)
      } else {
        osc.type = 'sawtooth'
        osc.frequency.setValueAtTime(160, ctx.currentTime) // Low buzz
        gain.gain.setValueAtTime(0.3, ctx.currentTime)
        osc.start()
        osc.stop(ctx.currentTime + 0.35)
      }
    } catch (e) {
      console.warn('Audio feedback failed:', e)
    }
  }

  // Load pending orders
  const fetchPendingOrders = async () => {
    setIsLoadingPending(true)
    try {
      const res = await axiosClient.get('/orders/photo-station/pending')
      setPendingOrders(res.data || [])
    } catch (e) {
      console.error('Failed to fetch pending verification orders', e)
    } finally {
      setIsLoadingPending(false)
    }
  }

  useEffect(() => {
    fetchPendingOrders()
  }, [])

  // Setup camera stream
  const startCamera = async () => {
    try {
      if (cameraStream) {
        cameraStream.getTracks().forEach((track) => track.stop())
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facingMode },
      })
      setCameraStream(stream)
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
    } catch (err) {
      console.warn('Camera stream not accessible:', err)
    }
  }

  useEffect(() => {
    startCamera()
    return () => {
      if (cameraStream) {
        cameraStream.getTracks().forEach((track) => track.stop())
      }
    }
  }, [facingMode])

  // Maintain input focus for scanner guns
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleBlur = () => {
    setTimeout(() => inputRef.current?.focus(), 150)
  }

  const toggleCamera = () => {
    setFacingMode((prev) => (prev === 'environment' ? 'user' : 'environment'))
  }

  const capturePhoto = (target: 'slip' | 'box') => {
    if (!videoRef.current) return
    const canvas = document.createElement('canvas')
    canvas.width = videoRef.current.videoWidth || 640
    canvas.height = videoRef.current.videoHeight || 480
    const ctx = canvas.getContext('2d')
    if (ctx) {
      ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height)
      const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
      if (target === 'slip') {
        setSlipPhotoData(dataUrl)
      } else {
        setBoxPhotoData(dataUrl)
      }
    }
  }

  const handleVerifySubmit = async (targetOrderNum?: string) => {
    const activeOrderNum = (targetOrderNum || orderNumber).trim()
    if (!activeOrderNum) return

    setIsProcessing(true)
    setStatusState('IDLE')
    setStatusMessage('')

    try {
      const payload = {
        order_number: activeOrderNum,
        slip_photo_path: slipPhotoData || `/volume1/photo/${activeOrderNum}_slip.jpg`,
        box_photo_path: boxPhotoData || `/volume1/photo/${activeOrderNum}_box.jpg`,
        extracted_tracking_number: trackingNumber.trim() || undefined,
      }

      const res = await axiosClient.post('/orders/photo-station/verify', payload)
      const { success, verify_status, message } = res.data

      if (success && verify_status === 'VERIFIED') {
        setStatusState('VERIFIED')
        setStatusMessage(message || 'Order Verified Successfully!')
        playSound('success')
        fetchPendingOrders()
        // Reset form for next order
        setOrderNumber('')
        setTrackingNumber('')
        setSlipPhotoData(null)
        setBoxPhotoData(null)
      } else if (verify_status === 'ERROR_MISSING_TRACKING') {
        setStatusState('ERROR_MISSING_TRACKING')
        setStatusMessage('Order found, but Tracking Number is MISSING!')
        playSound('error')
      } else {
        setStatusState('ERROR_NOT_FOUND')
        setStatusMessage(message || 'Order not found in the system.')
        playSound('error')
      }
    } catch (e: any) {
      setStatusState('ERROR_NOT_FOUND')
      setStatusMessage(e?.response?.data?.detail || 'Verification error occurred.')
      playSound('error')
    } finally {
      setIsProcessing(false)
      inputRef.current?.focus()
    }
  }

  return (
    <Box sx={{ p: { xs: 1, md: 3 } }} onClick={() => inputRef.current?.focus()}>
      {/* Header Banner */}
      <Paper
        elevation={0}
        sx={{
          p: 2,
          mb: 2,
          bgcolor: 'primary.dark',
          color: 'white',
          borderRadius: 2,
          display: 'flex',
          justify: 'space-between',
          alignItems: 'center',
        }}
      >
        <Box>
          <Typography variant="h5" fontWeight="bold" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <CameraAlt /> Photo Station & Order Verification
          </Typography>
          <Typography variant="body2" sx={{ opacity: 0.9 }}>
            Operator: {user?.username} ({user?.role})
          </Typography>
        </Box>
        <Chip
          icon={<VolumeUp sx={{ color: 'white !important' }} />}
          label="Audio Feedback Active"
          color="success"
          variant="filled"
        />
      </Paper>

      {/* Instant Feedback Status Flash Banner */}
      {statusState !== 'IDLE' && (
        <Paper
          elevation={4}
          sx={{
            p: 2.5,
            mb: 3,
            borderRadius: 2,
            bgcolor:
              statusState === 'VERIFIED'
                ? '#2e7d32'
                : statusState === 'ERROR_MISSING_TRACKING'
                ? '#d32f2f'
                : '#ed6c02',
            color: 'white',
            display: 'flex',
            alignItems: 'center',
            gap: 2,
          }}
        >
          {statusState === 'VERIFIED' ? (
            <CheckCircle sx={{ fontSize: 44 }} />
          ) : (
            <ErrorIcon sx={{ fontSize: 44 }} />
          )}
          <Box>
            <Typography variant="h6" fontWeight="bold">
              {statusState === 'VERIFIED'
                ? 'ORDER VERIFIED & PACKED'
                : statusState === 'ERROR_MISSING_TRACKING'
                ? 'ERROR: MISSING TRACKING NUMBER'
                : 'ORDER NOT FOUND'}
            </Typography>
            <Typography variant="body1">{statusMessage}</Typography>
          </Box>
        </Paper>
      )}

      <Grid container spacing={2}>
        {/* Left Column: Camera Feed & Photo Snapshots */}
        <Grid item xs={12} md={6}>
          <Card elevation={2} sx={{ borderRadius: 2 }}>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="h6" fontWeight="bold">
                  Camera Feed
                </Typography>
                <IconButton onClick={toggleCamera} color="primary" title="Switch Rear/Front Camera">
                  <Cameraswitch />
                </IconButton>
              </Box>

              {/* WebRTC Video Viewport */}
              <Box
                sx={{
                  position: 'relative',
                  width: '100%',
                  height: 240,
                  bgcolor: 'black',
                  borderRadius: 1,
                  overflow: 'hidden',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
              </Box>

              {/* Photo Capture Touch Buttons */}
              <Grid container spacing={1} sx={{ mt: 1.5 }}>
                <Grid item xs={6}>
                  <Button
                    fullWidth
                    variant={slipPhotoData ? 'contained' : 'outlined'}
                    color={slipPhotoData ? 'success' : 'primary'}
                    startIcon={<CameraAlt />}
                    onClick={() => capturePhoto('slip')}
                    size="large"
                  >
                    {slipPhotoData ? 'Slip Captured ✓' : 'Snap Slip'}
                  </Button>
                </Grid>
                <Grid item xs={6}>
                  <Button
                    fullWidth
                    variant={boxPhotoData ? 'contained' : 'outlined'}
                    color={boxPhotoData ? 'success' : 'primary'}
                    startIcon={<CameraAlt />}
                    onClick={() => capturePhoto('box')}
                    size="large"
                  >
                    {boxPhotoData ? 'Box Captured ✓' : 'Snap Box'}
                  </Button>
                </Grid>
              </Grid>

              {/* Captured Photo Previews */}
              <Box sx={{ display: 'flex', gap: 1, mt: 2 }}>
                {slipPhotoData && (
                  <Box sx={{ width: '50%', textAlign: 'center' }}>
                    <Typography variant="caption" color="text.secondary">Packing Slip</Typography>
                    <img src={slipPhotoData} alt="Slip" style={{ width: '100%', height: 90, objectFit: 'cover', borderRadius: 4 }} />
                  </Box>
                )}
                {boxPhotoData && (
                  <Box sx={{ width: '50%', textAlign: 'center' }}>
                    <Typography variant="caption" color="text.secondary">Box Photo</Typography>
                    <img src={boxPhotoData} alt="Box" style={{ width: '100%', height: 90, objectFit: 'cover', borderRadius: 4 }} />
                  </Box>
                )}
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Right Column: Scan & Order Verification Panel */}
        <Grid item xs={12} md={6}>
          <Card elevation={2} sx={{ borderRadius: 2, mb: 2 }}>
            <CardContent>
              <Typography variant="h6" fontWeight="bold" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                <QrCodeScanner color="primary" /> Scan & Verify Order
              </Typography>

              {/* Barcode Scanner Auto-Focus Field */}
              <TextField
                inputRef={inputRef}
                fullWidth
                label="Scan Order ID / Tracking Barcode"
                placeholder="Scan or type Order Number..."
                value={orderNumber}
                onChange={(e) => setOrderNumber(e.target.value)}
                onBlur={handleBlur}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleVerifySubmit()
                  }
                }}
                sx={{ mb: 2 }}
                autoFocus
              />

              <TextField
                fullWidth
                label="Optional Tracking Number (OCR / Manual)"
                placeholder="Tracking #..."
                value={trackingNumber}
                onChange={(e) => setTrackingNumber(e.target.value)}
                sx={{ mb: 2 }}
              />

              <Button
                fullWidth
                variant="contained"
                color="primary"
                size="large"
                disabled={isProcessing || !orderNumber.trim()}
                onClick={() => handleVerifySubmit()}
                sx={{ py: 1.5, fontSize: '1.1rem', fontWeight: 'bold' }}
              >
                {isProcessing ? <CircularProgress size={24} color="inherit" /> : 'VERIFY & PACK ORDER'}
              </Button>
            </CardContent>
          </Card>

          {/* Pending Queue List */}
          <Paper elevation={1} sx={{ p: 2, borderRadius: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Typography variant="subtitle1" fontWeight="bold">
                Unverified Orders Queue ({pendingOrders.length})
              </Typography>
              <IconButton size="small" onClick={fetchPendingOrders} disabled={isLoadingPending}>
                <Refresh fontSize="small" />
              </IconButton>
            </Box>

            <Box sx={{ maxHeight: 220, overflowY: 'auto' }}>
              {pendingOrders.length === 0 ? (
                <Typography variant="body2" color="text.secondary" align="center" sx={{ py: 2 }}>
                  All orders verified & ready for shipment!
                </Typography>
              ) : (
                pendingOrders.map((ord) => (
                  <Paper
                    key={ord.id}
                    variant="outlined"
                    sx={{
                      p: 1.2,
                      mb: 1,
                      display: 'flex',
                      justify: 'space-between',
                      alignItems: 'center',
                      cursor: 'pointer',
                      '&:hover': { bgcolor: 'action.hover' },
                    }}
                    onClick={() => {
                      setOrderNumber(ord.external_order_id)
                      if (ord.tracking_number) setTrackingNumber(ord.tracking_number)
                      inputRef.current?.focus()
                    }}
                  >
                    <Box>
                      <Typography variant="body2" fontWeight="bold">
                        {ord.external_order_id}
                      </Typography>
                      <Chip label={ord.platform} size="small" sx={{ fontSize: '0.7rem', height: 18 }} />
                    </Box>
                    <Button size="small" variant="contained" color="info" onClick={(e) => {
                      e.stopPropagation()
                      setOrderNumber(ord.external_order_id)
                      handleVerifySubmit(ord.external_order_id)
                    }}>
                      Verify
                    </Button>
                  </Paper>
                ))
              )}
            </Box>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  )
}
