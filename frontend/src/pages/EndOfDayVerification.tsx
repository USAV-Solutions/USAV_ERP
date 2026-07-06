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
import { CameraAlt, CloudUpload, CheckCircle, Warning, Cached } from '@mui/icons-material'
import axios from 'axios'

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
    stopCamera()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
    } catch (err) {
      console.error('Error accessing camera:', err)
    }
  }

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
  }

  const capturePhoto = () => {
    if (!videoRef.current || !canvasRef.current) return
    const video = videoRef.current
    const canvas = canvasRef.current
    const context = canvas.getContext('2d')
    if (!context) return

    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
    const dataUrl = canvas.toDataURL('image/jpeg')
    setShelfPhoto(dataUrl)
    stopCamera()
  }

  const handleVerify = async () => {
    if (!shelfPhoto && !manualCount) {
      alert('Please take a shelf photo or enter a manual box count.')
      return
    }

    setIsSubmitting(true)
    setResult(null)

    try {
      let uploadedPath = ''
      if (shelfPhoto) {
        // Convert captured data URL to a binary Blob
        const blob = await fetch(shelfPhoto).then((r) => r.blob())
        const fd = new FormData()
        fd.append('file', blob, 'packed_shelf.jpg')
        const uploadRes = await axios.post('/api/orders/photo-station/upload', fd)
        uploadedPath = uploadRes.data.path
      }

      // Verify box counts against verified orders database
      const verifyRes = await axios.post('/api/orders/photo-station/verify-shelf', {
        photo_path: uploadedPath || '/volume1/photo/shelf.jpg',
        manual_box_count: manualCount ? parseInt(manualCount, 10) : null,
      })

      setResult(verifyRes.data)
    } catch (err: any) {
      console.error('EOD Verification failed:', err)
      setResult({
        success: false,
        box_count: manualCount ? parseInt(manualCount, 10) : 0,
        verified_orders_count: 0,
        mismatch: true,
        message: err.response?.data?.detail || 'EOD verification request failed.',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  const resetVerification = () => {
    setShelfPhoto(null)
    setManualCount('')
    setResult(null)
    startCamera()
  }

  const triggerMockCapture = () => {
    setShelfPhoto('https://via.placeholder.com/640x480.png?text=Mock+Packed+Shelf+Photo')
    stopCamera()
  }

  return (
    <Box sx={{ maxWidth: 850, mx: 'auto', p: 2 }}>
      <Typography variant="h4" align="center" gutterBottom>
        End-of-Day Box Count Verification
      </Typography>
      <Typography variant="body1" align="center" color="text.secondary" paragraph>
        Warehouse Manager: Snap a photo of the completed shelf boxes ready for pickup to run automatic verification.
      </Typography>

      <Grid container spacing={3} sx={{ mt: 1 }}>
        {/* Left Side: Photo Capture */}
        <Grid item xs={12} md={7}>
          <Card raised sx={{ bgcolor: '#1e1e1e', color: 'white', minHeight: 320 }}>
            <CardContent sx={{ position: 'relative', p: 0, '&:last-child': { pb: 0 } }}>
              {!shelfPhoto ? (
                <Box sx={{ position: 'relative' }}>
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    style={{ width: '100%', height: 'auto', display: 'block' }}
                  />
                  <Box
                    sx={{
                      position: 'absolute',
                      bottom: 16,
                      left: '50%',
                      transform: 'translateX(-50%)',
                      display: 'flex',
                      gap: 2,
                    }}
                  >
                    <Button
                      variant="contained"
                      color="secondary"
                      startIcon={<CameraAlt />}
                      onClick={capturePhoto}
                      size="large"
                    >
                      Capture Shelf Photo
                    </Button>
                    <Button
                      variant="outlined"
                      color="inherit"
                      onClick={triggerMockCapture}
                      sx={{ bgcolor: 'rgba(0,0,0,0.5)' }}
                    >
                      Mock Capture
                    </Button>
                  </Box>
                </Box>
              ) : (
                <Box>
                  <img
                    src={shelfPhoto}
                    alt="Packed shelf"
                    style={{ width: '100%', height: 'auto', display: 'block' }}
                  />
                  <Button
                    fullWidth
                    variant="text"
                    color="inherit"
                    onClick={resetVerification}
                    startIcon={<Cached />}
                    sx={{ py: 1, bgcolor: '#333' }}
                  >
                    Retake Photo
                  </Button>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Right Side: Counting Validation Actions */}
        <Grid item xs={12} md={5}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Validation Engine
              </Typography>
              <Divider sx={{ mb: 2 }} />

              <TextField
                fullWidth
                label="Manual Box Count Override"
                type="number"
                value={manualCount}
                onChange={(e) => setManualCount(e.target.value)}
                placeholder="Optional manual count override"
                sx={{ mb: 3 }}
                helperText="Leave empty to use NVIDIA Locate Anything AI counting"
              />

              {isSubmitting ? (
                <Box sx={{ textAlign: 'center', my: 4 }}>
                  <CircularProgress />
                  <Typography sx={{ mt: 2 }}>Running AI Locate Anything object counts...</Typography>
                </Box>
              ) : (
                <>
                  {!result ? (
                    <Button
                      fullWidth
                      variant="contained"
                      color="primary"
                      size="large"
                      startIcon={<CloudUpload />}
                      onClick={handleVerify}
                    >
                      Run Verification
                    </Button>
                  ) : (
                    <Box>
                      {result.success ? (
                        <Alert
                          severity="success"
                          icon={<CheckCircle fontSize="inherit" />}
                          sx={{ mb: 3 }}
                        >
                          <AlertTitle>Count Verified</AlertTitle>
                          {result.message}
                          <Box sx={{ mt: 1 }}>
                            <strong>Shelf Box Count:</strong> {result.box_count} <br />
                            <strong>Verified Orders in DB:</strong> {result.verified_orders_count}
                          </Box>
                        </Alert>
                      ) : (
                        <Alert
                          severity="error"
                          icon={<Warning fontSize="inherit" />}
                          sx={{ mb: 3 }}
                        >
                          <AlertTitle>Discrepancy Warning</AlertTitle>
                          {result.message}
                          <Box sx={{ mt: 1 }}>
                            <strong>Shelf Box Count:</strong> {result.box_count} <br />
                            <strong>Verified Orders in DB:</strong> {result.verified_orders_count}
                          </Box>
                        </Alert>
                      )}

                      <Button
                        fullWidth
                        variant="contained"
                        color="secondary"
                        onClick={resetVerification}
                      >
                        Reset / Start New Verification
                      </Button>
                    </Box>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  )
}
