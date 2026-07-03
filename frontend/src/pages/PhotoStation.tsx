import { useState, useRef, useEffect } from 'react'
import {
  Box,
  Button,
  CircularProgress,
  Grid,
  Typography,
  TextField,
  Alert,
  AlertTitle,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  IconButton,
  InputAdornment,
} from '@mui/material'
import {
  CameraAlt,
  Replay,
  CloudUpload,
  CheckCircle,
  Warning,
  Close,
  Search,
  Refresh,
} from '@mui/icons-material'
import { createWorker } from 'tesseract.js'
import axios from 'axios'

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
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([])
  const [isLoadingOrders, setIsLoadingOrders] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  
  // Modal states
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [selectedOrder, setSelectedOrder] = useState<PendingOrder | null>(null)
  
  // Capture states inside modal
  const [captureStep, setCaptureStep] = useState<1 | 2 | 3>(1) // 1: Slip, 2: Box, 3: Save
  const [slipPhoto, setSlipPhoto] = useState<string | null>(null)
  const [boxPhoto, setBoxPhoto] = useState<string | null>(null)
  
  // OCR and extraction results
  const [detectedOrder, setDetectedOrder] = useState('')
  const [detectedTracking, setDetectedTracking] = useState('')
  const [detectedPlatform, setDetectedPlatform] = useState('')
  const [isOcrLoading, setIsOcrLoading] = useState(false)
  const [ocrError, setOcrError] = useState<string | null>(null)
  
  // Submit states
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState<{
    success: boolean
    message: string
    verify_status: string
  } | null>(null)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  // Fetch pending verification queue
  const fetchPendingOrders = async () => {
    setIsLoadingOrders(true)
    try {
      const res = await axios.get('/api/orders/photo-station/pending')
      setPendingOrders(res.data)
    } catch (err) {
      console.error('Failed to fetch pending orders:', err)
    } finally {
      setIsLoadingOrders(false)
    }
  }

  useEffect(() => {
    fetchPendingOrders()
  }, [])

  // Start webcam when modal is open and on step 1 or 2
  useEffect(() => {
    if (isModalOpen && (captureStep === 1 || captureStep === 2)) {
      startCamera()
    } else {
      stopCamera()
    }
    return () => stopCamera()
  }, [isModalOpen, captureStep])

  const startCamera = async () => {
    stopCamera()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' } // Prefer back camera on mobile
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
    } catch (err) {
      console.error('Error starting camera:', err)
    }
  }

  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
  }

  const handleOpenCapture = (order: PendingOrder) => {
    setSelectedOrder(order)
    setCaptureStep(1)
    setSlipPhoto(null)
    setBoxPhoto(null)
    setDetectedOrder('')
    setDetectedTracking('')
    setDetectedPlatform('')
    setOcrError(null)
    setSubmitResult(null)
    setIsModalOpen(true)
  }

  const handleCloseModal = () => {
    stopCamera()
    setIsModalOpen(false)
    setSelectedOrder(null)
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

    if (captureStep === 1) {
      setSlipPhoto(dataUrl)
      runOCR(dataUrl)
    } else {
      setBoxPhoto(dataUrl)
      setCaptureStep(3)
    }
  }

  // Advanced OCR regex-based parser
  const runOCR = async (dataUrl: string) => {
    setIsOcrLoading(true)
    setOcrError(null)
    try {
      const worker = await createWorker('eng')
      const ret = await worker.recognize(dataUrl)
      await worker.terminate()
      
      const text = ret.data.text
      console.log('OCR Raw Text Block:', text)

      // 1. Recognize Platforms and Packing Slip Formats
      let platform = ''
      if (/amazon/i.test(text)) platform = 'AMAZON'
      else if (/ebay/i.test(text)) platform = 'EBAY'
      else if (/ecwid/i.test(text)) platform = 'ECWID'
      else if (/walmart/i.test(text)) platform = 'WALMART'
      setDetectedPlatform(platform)

      // 2. Extract Order Number
      // Amazon order ID: 114-0294090-0548272
      const amazonOrder = text.match(/\b\d{3}-\d{7}-\d{7}\b/)
      // eBay order ID: 12-34567-89012 or standard numeric sequence
      const ebayOrder = text.match(/\b\d{2}-\d{5}-\d{5}\b/)
      // Generic order: SO-xxxx or 5-to-15 digit sequence
      const genericOrder = text.match(/\b(?:SO-)?\d{5,15}\b/i)

      let orderNum = ''
      if (amazonOrder) orderNum = amazonOrder[0]
      else if (ebayOrder) orderNum = ebayOrder[0]
      else if (genericOrder) orderNum = genericOrder[0]
      setDetectedOrder(orderNum)

      // 3. Extract Shipping Carrier Tracking Number
      // UPS: 1Z[A-Z0-9]{16}
      const upsTrack = text.replace(/\s+/g, '').match(/\b1Z[A-Z0-9]{16}\b/i)
      // USPS: 92/94 followed by 20 digits or generic 22 digits starting with 9
      const uspsTrack = text.replace(/\s+/g, '').match(/\b9[24]\d{20}\b/) || text.replace(/\s+/g, '').match(/\b\d{20,22}\b/)
      // FedEx: 12 or 15 digits
      const fedexTrack = text.replace(/\s+/g, '').match(/\b\d{12}\b/) || text.replace(/\s+/g, '').match(/\b\d{15}\b/)

      let trackNum = ''
      if (upsTrack) trackNum = upsTrack[0]
      else if (uspsTrack && uspsTrack[0].startsWith('9')) trackNum = uspsTrack[0]
      else if (fedexTrack) trackNum = fedexTrack[0]
      setDetectedTracking(trackNum)

      if (!orderNum && !trackNum) {
        setOcrError('Could not recognize order ID or tracking barcode. Try taking the photo under direct light.')
      }
    } catch (err) {
      console.error('OCR analysis failed:', err)
      setOcrError('Failed to read image. Please enter details manually.')
    } finally {
      setIsOcrLoading(false)
    }
  }

  const handleUploadAndSave = async () => {
    if (!selectedOrder) return
    const orderIdToVerify = (detectedOrder || selectedOrder.external_order_id || '').trim()
    if (!orderIdToVerify) {
      alert('Please detect or manually enter the Order Number reference first.')
      return
    }

    setIsSubmitting(true)
    setSubmitResult(null)

    try {
      // 1. Convert captured data URLs to binary Blobs
      const slipBlob = await fetch(slipPhoto!).then((r) => r.blob())
      const boxBlob = await fetch(boxPhoto!).then((r) => r.blob())

      // 2. Upload Slip
      const fd1 = new FormData()
      fd1.append('file', slipBlob, `${orderIdToVerify}_slip.jpg`)
      const res1 = await axios.post('/api/orders/photo-station/upload', fd1)
      const slipPath = res1.data.path

      // 3. Upload Box
      const fd2 = new FormData()
      fd2.append('file', boxBlob, `${orderIdToVerify}_box.jpg`)
      const res2 = await axios.post('/api/orders/photo-station/upload', fd2)
      const boxPath = res2.data.path

      // 4. Verify & save tracking in Backend
      const verifyRes = await axios.post('/api/orders/photo-station/verify', {
        order_number: orderIdToVerify,
        slip_photo_path: slipPath,
        box_photo_path: boxPath,
        extracted_tracking_number: detectedTracking || null
      })

      setSubmitResult(verifyRes.data)
      if (verifyRes.data.success) {
        fetchPendingOrders() // Refresh pending list
      }
    } catch (err: any) {
      console.error('Save failed:', err)
      setSubmitResult({
        success: false,
        message: err.response?.data?.detail || 'Photo Station upload failed.',
        verify_status: 'ERROR_MISSING_TRACKING',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  const triggerMockCapture = () => {
    if (!selectedOrder) return
    const orderId = selectedOrder.external_order_id || `SO-${Math.floor(100000 + Math.random() * 900000)}`
    if (captureStep === 1) {
      setSlipPhoto('https://via.placeholder.com/640x480.png?text=Mock+Slip+Photo')
      setDetectedOrder(orderId)
      setDetectedPlatform(selectedOrder.platform || 'MANUAL')
      setDetectedTracking(`94001${Math.floor(10000000000000000 + Math.random() * 9000000000000000)}`)
    } else {
      setBoxPhoto('https://via.placeholder.com/640x480.png?text=Mock+Box+Photo')
      setCaptureStep(3)
    }
  }

  // Filter orders by typing last 4 to 6 characters (smart suffix matching)
  const filteredOrders = pendingOrders.filter((order) => {
    if (!searchQuery) return true
    const query = searchQuery.trim().toLowerCase()
    
    // Exact match, partial match, or suffix matching for order number
    const extId = order.external_order_id.toLowerCase()
    const extNum = (order.external_order_number || '').toLowerCase()
    
    return (
      extId.includes(query) ||
      extNum.includes(query) ||
      extId.endsWith(query) ||
      extNum.endsWith(query)
    )
  })

  return (
    <Box sx={{ p: 1 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Photo Station Verification Queue
      </Typography>

      {/* Filter and Refresh Row */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
        <TextField
          sx={{ flexGrow: 1, maxWidth: 500 }}
          placeholder="Smart Filter (type last 4-6 digits of Order ID...)"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Search />
              </InputAdornment>
            ),
          }}
        />
        <Button
          variant="outlined"
          startIcon={<Refresh />}
          onClick={fetchPendingOrders}
          disabled={isLoadingOrders}
        >
          Refresh List
        </Button>
        <Button
          variant="contained"
          color="secondary"
          startIcon={<CameraAlt />}
          onClick={() => handleOpenCapture({
            id: 0,
            external_order_id: '',
            platform: 'MANUAL',
            total_amount: 0
          })}
        >
          Direct Capture
        </Button>
      </Box>

      {isLoadingOrders ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress />
        </Box>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Platform</TableCell>
                <TableCell>Order ID</TableCell>
                <TableCell>Order Number</TableCell>
                <TableCell>Date Placed</TableCell>
                <TableCell>Total Amount</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredOrders.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} align="center" sx={{ py: 6 }}>
                    No pending orders without tracking in the last 10 days.
                  </TableCell>
                </TableRow>
              ) : (
                filteredOrders.map((order) => (
                  <TableRow key={order.id} hover>
                    <TableCell>
                      <Chip
                        label={order.platform}
                        color={
                          order.platform === 'AMAZON'
                            ? 'primary'
                            : order.platform === 'EBAY'
                            ? 'secondary'
                            : 'default'
                        }
                        size="small"
                      />
                    </TableCell>
                    <TableCell sx={{ fontWeight: 'bold' }}>{order.external_order_id}</TableCell>
                    <TableCell>{order.external_order_number || '-'}</TableCell>
                    <TableCell>
                      {order.ordered_at ? new Date(order.ordered_at).toLocaleDateString() : '-'}
                    </TableCell>
                    <TableCell>${order.total_amount.toFixed(2)}</TableCell>
                    <TableCell align="right">
                      <Button
                        variant="contained"
                        color="primary"
                        startIcon={<CameraAlt />}
                        onClick={() => handleOpenCapture(order)}
                      >
                        Capture Pack
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Modal Dialog for Camera Capture */}
      <Dialog
        open={isModalOpen}
        onClose={handleCloseModal}
        maxWidth="md"
        fullWidth
        disableEscapeKeyDown
      >
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="h6">
            Pack Verification: {selectedOrder?.external_order_id || 'Direct Capture'} ({selectedOrder?.platform || 'MANUAL'})
          </Typography>
          <IconButton onClick={handleCloseModal}>
            <Close />
          </IconButton>
        </DialogTitle>

        <DialogContent dividers>
          <Grid container spacing={2}>
            {/* Camera Viewport / Captured Preview */}
            <Grid item xs={12} md={7}>
              <Box
                sx={{
                  width: '100%',
                  bgcolor: '#121212',
                  borderRadius: 2,
                  overflow: 'hidden',
                  position: 'relative',
                  minHeight: 280,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {(captureStep === 1 || captureStep === 2) ? (
                  <Box sx={{ width: '100%', position: 'relative' }}>
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
                      >
                        {captureStep === 1 ? 'Capture Slip & Label' : 'Capture Packed Box'}
                      </Button>
                      <Button
                        variant="outlined"
                        color="inherit"
                        sx={{ bgcolor: 'rgba(0,0,0,0.5)' }}
                        onClick={triggerMockCapture}
                      >
                        Mock Capture
                      </Button>
                    </Box>
                  </Box>
                ) : (
                  <Grid container spacing={0}>
                    <Grid item xs={6}>
                      <Typography align="center" variant="caption" sx={{ display: 'block', bgcolor: '#333', color: 'white', py: 0.5 }}>
                        Slip & Label
                      </Typography>
                      <img src={slipPhoto || ''} alt="Slip" style={{ width: '100%', display: 'block' }} />
                    </Grid>
                    <Grid item xs={6}>
                      <Typography align="center" variant="caption" sx={{ display: 'block', bgcolor: '#333', color: 'white', py: 0.5 }}>
                        Box Photo
                      </Typography>
                      <img src={boxPhoto || ''} alt="Box" style={{ width: '100%', display: 'block' }} />
                    </Grid>
                  </Grid>
                )}
              </Box>
            </Grid>

            {/* Instruction / Metadata Verification info */}
            <Grid item xs={12} md={5}>
              {captureStep === 1 && (
                <Box>
                  <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
                    Step 1: Capture Packing Slip & Label
                  </Typography>
                  <Typography variant="body2" color="text.secondary" paragraph>
                    Capture both paper forms in one frame. The smart OCR engine will extract Order ID, Platform, and Tracking barcodes.
                  </Typography>

                  {isOcrLoading && (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, my: 2 }}>
                      <CircularProgress size={20} />
                      <Typography variant="body2">Analyzing packing parameters...</Typography>
                    </Box>
                  )}

                  {ocrError && (
                    <Alert severity="warning" sx={{ mb: 2 }}>
                      <AlertTitle>Image Quality Notice</AlertTitle>
                      {ocrError}
                    </Alert>
                  )}

                  {/* Detected Metadata Fields */}
                  <TextField
                    fullWidth
                    size="small"
                    label="OCR Detected Order ID"
                    value={detectedOrder}
                    onChange={(e) => setDetectedOrder(e.target.value)}
                    sx={{ mb: 2 }}
                    helperText={detectedOrder ? `Extracted from document` : `Enter manually if undetected`}
                  />

                  <TextField
                    fullWidth
                    size="small"
                    label="OCR Detected Tracking Barcode"
                    value={detectedTracking}
                    onChange={(e) => setDetectedTracking(e.target.value)}
                    sx={{ mb: 2 }}
                    helperText={detectedTracking ? `Carrier Tracking Number` : `Enter manually if barcode undetected`}
                  />

                  {detectedPlatform && (
                    <Alert severity="info" sx={{ mb: 2, py: 0 }}>
                      Recognized platform source: <strong>{detectedPlatform}</strong>
                    </Alert>
                  )}

                  {slipPhoto && (
                    <Button
                      fullWidth
                      variant="contained"
                      onClick={() => setCaptureStep(2)}
                      disabled={isOcrLoading}
                    >
                      Next: Capture Packed Box
                    </Button>
                  )}
                </Box>
              )}

              {captureStep === 2 && (
                <Box>
                  <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
                    Step 2: Capture Finished Packed Box
                  </Typography>
                  <Typography variant="body2" color="text.secondary" paragraph>
                    Align the finished shipping package inside the frame and snap the packed photo presentation.
                  </Typography>

                  <Button
                    fullWidth
                    variant="outlined"
                    startIcon={<Replay />}
                    onClick={() => setCaptureStep(1)}
                  >
                    Go Back to Slip
                  </Button>
                </Box>
              )}

              {captureStep === 3 && (
                <Box>
                  <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
                    Step 3: Save Verification Status
                  </Typography>

                  <TextField
                    fullWidth
                    size="small"
                    label="Final Order Number Reference"
                    value={detectedOrder || selectedOrder?.external_order_id}
                    onChange={(e) => setDetectedOrder(e.target.value)}
                    sx={{ mb: 2 }}
                  />

                  <TextField
                    fullWidth
                    size="small"
                    label="Final Tracking Barcode"
                    value={detectedTracking}
                    onChange={(e) => setDetectedTracking(e.target.value)}
                    sx={{ mb: 3 }}
                  />

                  {isSubmitting ? (
                    <Box sx={{ textAlign: 'center', my: 2 }}>
                      <CircularProgress size={28} />
                      <Typography variant="body2" sx={{ mt: 1 }}>Uploading files to Synology NAS...</Typography>
                    </Box>
                  ) : (
                    <>
                      {!submitResult ? (
                        <Button
                          fullWidth
                          variant="contained"
                          color="primary"
                          startIcon={<CloudUpload />}
                          onClick={handleUploadAndSave}
                          size="large"
                        >
                          Upload & Validate
                        </Button>
                      ) : (
                        <Box>
                          {submitResult.success ? (
                            <Alert
                              severity="success"
                              icon={<CheckCircle fontSize="inherit" />}
                              sx={{ mb: 2 }}
                            >
                              <AlertTitle>Verification Completed</AlertTitle>
                              {submitResult.message}
                            </Alert>
                          ) : (
                            <Alert
                              severity="error"
                              icon={<Warning fontSize="inherit" />}
                              sx={{ mb: 2 }}
                            >
                              <AlertTitle>Verification Alert</AlertTitle>
                              {submitResult.message}
                            </Alert>
                          )}
                          <Button
                            fullWidth
                            variant="contained"
                            color="secondary"
                            onClick={handleCloseModal}
                          >
                            Close & Continue
                          </Button>
                        </Box>
                      )}
                    </>
                  )}
                </Box>
              )}
            </Grid>
          </Grid>
        </DialogContent>

        <DialogActions>
          <Button onClick={handleCloseModal} color="inherit">
            Cancel
          </Button>
        </DialogActions>
      </Dialog>

      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </Box>
  )
}
