import { useState, useRef, useEffect } from 'react'
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Grid,
  Typography,
  TextField,
  Alert,
  AlertTitle,
  Divider,
} from '@mui/material'
import { CameraAlt, CloudUpload, CheckCircle, Warning, Cached, LocalShipping } from '@mui/icons-material'
import axiosClient from '../api/axiosClient'

export default function EndOfDayVerification() {
  const [shelfPhoto, setShelfPhoto] = useState<string | null>(null)
  const [manualCount, setManualCount] = useState<string>('')
  
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false)
  const [result, setResult] = useState<{
    success: boolean
    box_count: number
    verified_orders_count: number
    mismatch: boolean
    message: string
  } | null>(null)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  useEffect(() => {
    startCamera()
    return () => {
      stopCamera()
    }
  }, [])

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
    } catch (err) {
      console.warn("Could not access camera for shelf verification:", err)
    }
  }

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop())
    }
  }

  const capturePhoto = () => {
    if (videoRef.current && canvasRef.current) {
      const context = canvasRef.current.getContext('2d')
      if (context) {
        canvasRef.current.width = videoRef.current.videoWidth
        canvasRef.current.height = videoRef.current.videoHeight
        context.drawImage(videoRef.current, 0, 0)
        const dataUrl = canvasRef.current.toDataURL('image/jpeg')
        setShelfPhoto(dataUrl)
      }
    }
  }

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      const reader = new FileReader()
      reader.onloadend = () => {
        setShelfPhoto(reader.result as string)
      }
      reader.readAsDataURL(file)
    }
  }

  const handleSubmit = async () => {
    setIsSubmitting(true)
    setResult(null)

    try {
      const payload = {
        photo_path: shelfPhoto || '/volume1/photo/shelf_end_of_day.jpg',
        manual_box_count: manualCount.trim() ? parseInt(manualCount.trim(), 10) : undefined,
      }

      const res = await axiosClient.post('/orders/photo-station/verify-shelf', payload)
      setResult(res.data)
    } catch (e: any) {
      setResult({
        success: false,
        box_count: 0,
        verified_orders_count: 0,
        mismatch: true,
        message: e?.response?.data?.detail || 'Shelf count verification failed.',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Box sx={{ p: { xs: 2, md: 4 }, maxWidth: 1000, margin: '0 auto' }}>
      <Typography variant="h4" gutterBottom sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: 1 }}>
        <LocalShipping color="primary" fontSize="large" /> End-of-Day Shelf Verification
      </Typography>
      <Typography variant="body1" color="text.secondary" paragraph>
        Audit physical shelf box count against verified orders before dispatch.
      </Typography>

      {result && (
        <Alert
          severity={result.success ? "success" : "error"}
          icon={result.success ? <CheckCircle fontSize="inherit" /> : <Warning fontSize="inherit" />}
          sx={{ mb: 3 }}
        >
          <AlertTitle sx={{ fontWeight: 'bold' }}>
            {result.success ? "SHELF COUNT MATCHED — READY TO SHIP" : "COUNT MISMATCH WARNING"}
          </AlertTitle>
          {result.message} — Verified Orders: <strong>{result.verified_orders_count}</strong> | Shelf Count: <strong>{result.box_count}</strong>
        </Alert>
      )}

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card elevation={3}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Shelf Photo Stream
              </Typography>
              <Box sx={{ position: 'relative', width: '100%', height: 260, bgcolor: 'black', borderRadius: 1, overflow: 'hidden', mb: 2 }}>
                <video ref={videoRef} autoPlay playsInline muted style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                <canvas ref={canvasRef} style={{ display: 'none' }} />
              </Box>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button fullWidth variant="contained" startIcon={<CameraAlt />} onClick={capturePhoto}>
                  Snap Shelf
                </Button>
                <Button component="label" variant="outlined" startIcon={<CloudUpload />}>
                  Upload
                  <input type="file" accept="image/*" hidden onChange={handleFileUpload} />
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card elevation={3}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Manual Audit & Run
              </Typography>

              {shelfPhoto && (
                <Box sx={{ mb: 2, textAlign: 'center' }}>
                  <Typography variant="caption" display="block">Captured Shelf Image</Typography>
                  <img src={shelfPhoto} alt="Shelf Preview" style={{ width: '100%', maxHeight: 120, objectFit: 'cover', borderRadius: 4 }} />
                </Box>
              )}

              <TextField
                fullWidth
                type="number"
                label="Manual Shelf Box Count (Optional)"
                placeholder="Enter box count on shelf..."
                value={manualCount}
                onChange={(e) => setManualCount(e.target.value)}
                sx={{ mb: 3 }}
              />

              <Button
                fullWidth
                variant="contained"
                color="primary"
                size="large"
                disabled={isSubmitting}
                onClick={handleSubmit}
                sx={{ py: 1.5, fontWeight: 'bold' }}
              >
                {isSubmitting ? <CircularProgress size={24} color="inherit" /> : 'RUN SHELF VERIFICATION'}
              </Button>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  )
}
