import React, { useState, useEffect } from 'react'
import {
  Box,
  Typography,
  Paper,
  Button,
  Grid,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  Alert,
  Breadcrumbs,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  LinearProgress,
} from '@mui/material'
import {
  CloudUpload,
  AutoAwesome,
  CheckCircle,
  Error as ErrorIcon,
  Warning,
  Speed,
  FindInPage,
  Inventory,
  Dns,
  Refresh,
  PlayArrow,
} from '@mui/icons-material'
import axiosClient from '../api/axiosClient'

interface DiagnosticResult {
  success: boolean
  filename: string
  latency_ms: number
  is_valid_packing_photo: boolean
  platform: string
  order_id: string
  tracking_number: string
  sku_on_slip?: string
  detected_physical_item: string
  expected_erp_item?: string
  item_match: boolean
  confidence_score: number
  status: string
  message: string
  image_data_url?: string
  previewUrl?: string
}

export default function PhotoStationDiagnostics() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [isDiagnosing, setIsDiagnosing] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamProgress, setStreamProgress] = useState<{ current: number; total: number; filename: string }>({ current: 0, total: 0, filename: '' })
  const [nasLimit, setNasLimit] = useState<number>(5)
  const [resultsHistory, setResultsHistory] = useState<DiagnosticResult[]>([])
  const [nasError, setNasError] = useState<string | null>(null)

  const nasFolderPath = '/USAV Media/Packing Shipping/Packing Photos/Packing Station 2/2026/Q2 26'

  // Auto-stream NAS photos on page load
  useEffect(() => {
    startNasAutoStream(5)
  }, [])

  const startNasAutoStream = async (limit: number = nasLimit) => {
    setIsStreaming(true)
    setNasError(null)
    setResultsHistory([])

    try {
      // 1. Fetch NAS file list
      const listRes = await axiosClient.get('/orders/photo-station/nas-files', {
        params: { folder_path: nasFolderPath, limit: limit }
      })

      const filePaths: string[] = listRes.data.files || []
      if (filePaths.length === 0) {
        setNasError('No image files found in NAS folder.')
        setIsStreaming(false)
        return
      }

      setStreamProgress({ current: 0, total: filePaths.length, filename: 'Initializing stream...' })

      // 2. Stream each NAS file one-by-one in real-time
      for (let i = 0; i < filePaths.length; i++) {
        const filePath = filePaths[i]
        const filename = filePath.split('/').pop() || filePath
        setStreamProgress({ current: i + 1, total: filePaths.length, filename: filename })

        try {
          const diagRes = await axiosClient.post('/orders/photo-station/diagnose-nas-file', {
            file_path: filePath
          })

          const data: DiagnosticResult = {
            ...diagRes.data,
            previewUrl: diagRes.data.image_data_url || undefined
          }

          // Instantly pop the result card onto the screen!
          setResultsHistory((prev) => [data, ...prev])
        } catch (err: any) {
          console.error(`Failed to diagnose ${filename}:`, err)
        }
      }
    } catch (err: any) {
      console.error('Failed to list NAS files:', err)
      setNasError(err?.response?.data?.detail || 'Failed to connect to Synology NAS over QuickConnect.')
    } finally {
      setIsStreaming(false)
    }
  }

  const handleFileSelect = (file: File) => {
    setSelectedFile(file)
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelect(e.dataTransfer.files[0])
    }
  }

  const runSingleDiagnosis = async () => {
    if (!selectedFile) return

    setIsDiagnosing(true)
    const formData = new FormData()
    formData.append('file', selectedFile)

    try {
      const res = await axiosClient.post('/orders/photo-station/diagnose', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      const data: DiagnosticResult = {
        ...res.data,
        previewUrl: previewUrl || res.data.image_data_url || undefined,
      }

      setResultsHistory((prev) => [data, ...prev])
    } catch (err: any) {
      console.error('Diagnosis failed:', err)
      const errorResult: DiagnosticResult = {
        success: false,
        filename: selectedFile.name,
        latency_ms: 0,
        is_valid_packing_photo: false,
        platform: 'UNKNOWN',
        order_id: '',
        tracking_number: '',
        detected_physical_item: 'Failed to process',
        item_match: false,
        confidence_score: 0.0,
        status: 'ERROR',
        message: err?.response?.data?.detail || 'Diagnostic execution failed.',
        previewUrl: previewUrl || undefined,
      }
      setResultsHistory((prev) => [errorResult, ...prev])
    } finally {
      setIsDiagnosing(false)
    }
  }

  const getStatusChip = (status: string) => {
    switch (status) {
      case 'CORRECT':
        return <Chip icon={<CheckCircle />} label="CORRECT & VERIFIED" color="success" sx={{ fontWeight: 'bold' }} />
      case 'MISSING_TRACKING':
        return <Chip icon={<Warning />} label="MISSING TRACKING" color="error" sx={{ fontWeight: 'bold' }} />
      case 'ORDER_NOT_IN_ERP':
        return <Chip icon={<Warning />} label="PARSED (ORDER NOT IN ERP)" color="warning" sx={{ fontWeight: 'bold' }} />
      case 'NO_PACKING_SLIP':
        return <Chip icon={<FindInPage />} label="NO PACKING SLIP (PARTS PHOTO)" color="default" />
      default:
        return <Chip icon={<ErrorIcon />} label="ERROR" color="error" />
    }
  }

  return (
    <Box sx={{ p: { xs: 2, md: 3 } }}>
      {/* Top Banner & Path */}
      <Paper elevation={0} sx={{ p: 2.5, mb: 3, bgcolor: 'background.paper', borderRadius: 2, border: '1px solid #e0e0e0' }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 2 }}>
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Dns color="primary" />
              <Typography variant="h6" fontWeight="bold">
                Synology NAS Live AI Streaming Sandbox
              </Typography>
              {isStreaming ? (
                <Chip icon={<CircularProgress size={14} color="inherit" />} label="STREAMING LIVE" color="primary" size="small" sx={{ fontWeight: 'bold' }} />
              ) : (
                <Chip label="QUICKCONNECT CONNECTED" color="success" size="small" variant="outlined" sx={{ fontWeight: 'bold' }} />
              )}
            </Box>
            <Breadcrumbs separator="›" aria-label="breadcrumb" sx={{ mt: 0.5 }}>
              <Typography variant="body2" color="primary.main" fontWeight="bold">USAV Media</Typography>
              <Typography variant="body2">Packing Shipping</Typography>
              <Typography variant="body2">Packing Photos</Typography>
              <Typography variant="body2">Packing Station 2</Typography>
              <Typography variant="body2">2026</Typography>
              <Typography variant="body2" color="primary.main" fontWeight="bold">Q2 26</Typography>
            </Breadcrumbs>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>Batch Limit</InputLabel>
              <Select
                value={nasLimit}
                label="Batch Limit"
                onChange={(e) => {
                  const val = Number(e.target.value)
                  setNasLimit(val)
                  startNasAutoStream(val)
                }}
              >
                <MenuItem value={3}>3 Sample Photos</MenuItem>
                <MenuItem value={5}>5 Sample Photos</MenuItem>
                <MenuItem value={10}>10 Sample Photos</MenuItem>
                <MenuItem value={20}>20 Sample Photos</MenuItem>
              </Select>
            </FormControl>

            <Button
              variant="contained"
              color="primary"
              disabled={isStreaming}
              startIcon={isStreaming ? <CircularProgress size={18} color="inherit" /> : <PlayArrow />}
              onClick={() => startNasAutoStream(nasLimit)}
              sx={{ fontWeight: 'bold', py: 1 }}
            >
              {isStreaming ? 'STREAMING...' : 'RE-STREAM NAS PHOTOS'}
            </Button>
          </Box>
        </Box>

        {/* Live Streaming Progress Bar */}
        {isStreaming && (
          <Box sx={{ mt: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="caption" color="primary.main" fontWeight="bold">
                Streaming & Diagnosing Photo {streamProgress.current} of {streamProgress.total}: {streamProgress.filename}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {Math.round((streamProgress.current / (streamProgress.total || 1)) * 100)}%
              </Typography>
            </Box>
            <LinearProgress variant="determinate" value={(streamProgress.current / (streamProgress.total || 1)) * 100} sx={{ height: 6, borderRadius: 3 }} />
          </Box>
        )}
      </Paper>

      {/* Main Grid */}
      <Grid container spacing={3}>
        {/* Left Side: Drag & Drop Sandbox */}
        <Grid item xs={12} md={4}>
          <Card elevation={2} sx={{ borderRadius: 2 }}>
            <CardContent>
              <Typography variant="h6" fontWeight="bold" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                <AutoAwesome color="primary" /> Single Photo Upload
              </Typography>

              <Box
                onDragOver={(e) => e.preventDefault()}
                onDrop={handleDrop}
                sx={{
                  border: '2px dashed',
                  borderColor: selectedFile ? 'primary.main' : 'grey.400',
                  borderRadius: 2,
                  p: 2.5,
                  textAlign: 'center',
                  bgcolor: selectedFile ? 'action.hover' : 'background.default',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                  '&:hover': { borderColor: 'primary.main', bgcolor: 'action.hover' },
                }}
              >
                <input
                  type="file"
                  accept="image/*"
                  id="sample-file-input"
                  style={{ display: 'none' }}
                  onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
                />
                <label htmlFor="sample-file-input" style={{ cursor: 'pointer', width: '100%', display: 'block' }}>
                  <CloudUpload color="primary" sx={{ fontSize: 40, mb: 0.5 }} />
                  <Typography variant="subtitle2" fontWeight="bold">
                    {selectedFile ? selectedFile.name : 'Choose Local Photo or Drag & Drop'}
                  </Typography>
                </label>
              </Box>

              {previewUrl && (
                <Box sx={{ mt: 2, textAlign: 'center' }}>
                  <img
                    src={previewUrl}
                    alt="Preview"
                    style={{ width: '100%', maxHeight: 180, objectFit: 'contain', borderRadius: 8, border: '1px solid #e0e0e0' }}
                  />
                </Box>
              )}

              <Button
                fullWidth
                variant="outlined"
                color="primary"
                size="large"
                disabled={!selectedFile || isDiagnosing}
                onClick={runSingleDiagnosis}
                startIcon={<AutoAwesome />}
                sx={{ mt: 2, py: 1.2, fontWeight: 'bold' }}
              >
                {isDiagnosing ? <CircularProgress size={20} color="inherit" /> : 'DIAGNOSE UPLOADED PHOTO'}
              </Button>
            </CardContent>
          </Card>
        </Grid>

        {/* Right Side: Streaming Results Cards */}
        <Grid item xs={12} md={8}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6" fontWeight="bold" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <FindInPage color="primary" /> Live Streaming Results ({resultsHistory.length})
            </Typography>
            {resultsHistory.length > 0 && (
              <Button size="small" variant="outlined" startIcon={<Refresh />} onClick={() => setResultsHistory([])}>
                Clear
              </Button>
            )}
          </Box>

          {nasError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {nasError}
            </Alert>
          )}

          {resultsHistory.length === 0 && !isStreaming ? (
            <Paper elevation={1} sx={{ p: 5, textAlign: 'center', borderRadius: 2, bgcolor: 'background.paper' }}>
              <Inventory sx={{ fontSize: 56, color: 'text.secondary', mb: 1.5 }} />
              <Typography variant="h6" fontWeight="bold" color="text.primary" sx={{ mb: 1 }}>
                No diagnostic results visible
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 460, mx: 'auto', mb: 3 }}>
                Click <strong>"RE-STREAM NAS PHOTOS"</strong> to connect to your Synology NAS over QuickConnect and stream Gemini 3.5 Flash diagnostic results live onto your screen.
              </Typography>
              <Button
                variant="contained"
                color="primary"
                startIcon={<PlayArrow />}
                onClick={() => startNasAutoStream(nasLimit)}
                sx={{ fontWeight: 'bold' }}
              >
                START LIVE STREAM NOW
              </Button>
            </Paper>
          ) : (
            resultsHistory.map((res, index) => (
              <Card key={index} elevation={2} sx={{ mb: 2.5, borderRadius: 2, overflow: 'hidden', transition: 'all 0.3s' }}>
                <CardContent sx={{ p: 2.5 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="subtitle1" fontWeight="bold">
                        {res.filename}
                      </Typography>
                      {getStatusChip(res.status)}
                    </Box>
                    <Chip
                      icon={<Speed />}
                      label={`${res.latency_ms} ms`}
                      size="small"
                      variant="outlined"
                      color="info"
                    />
                  </Box>

                  <Divider sx={{ my: 1.5 }} />

                  <Grid container spacing={2}>
                    <Grid item xs={12} sm={4}>
                      {res.previewUrl || res.image_data_url ? (
                        <img
                          src={res.previewUrl || res.image_data_url}
                          alt="Packaging Photo Thumbnail"
                          style={{ width: '100%', height: 140, objectFit: 'cover', borderRadius: 6, border: '1px solid #e0e0e0' }}
                        />
                      ) : (
                        <Box sx={{ height: 140, bgcolor: 'action.hover', borderRadius: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Inventory color="disabled" />
                        </Box>
                      )}
                    </Grid>

                    <Grid item xs={12} sm={8}>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 1 }}>
                        <Chip label={`Platform: ${res.platform}`} size="small" variant="outlined" />
                        {res.order_id && <Chip label={`Order: ${res.order_id}`} size="small" color="primary" variant="outlined" sx={{ fontWeight: 'bold' }} />}
                        {res.tracking_number && <Chip label={`Tracking: ${res.tracking_number}`} size="small" color="secondary" variant="outlined" />}
                        {res.sku_on_slip && <Chip label={`SKU: ${res.sku_on_slip}`} size="small" variant="outlined" />}
                      </Box>

                      <Box sx={{ p: 1.5, bgcolor: 'background.default', borderRadius: 1.5, border: '1px solid #e0e0e0' }}>
                        <Typography variant="caption" color="primary.main" fontWeight="bold" display="block">
                          AI VISUAL PHYSICAL ITEM IDENTIFICATION:
                        </Typography>
                        <Typography variant="body2" fontWeight="medium">
                          {res.detected_physical_item}
                        </Typography>
                        {res.expected_erp_item && (
                          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                            ERP Database Item: <strong>{res.expected_erp_item}</strong>
                          </Typography>
                        )}
                      </Box>

                      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                        {res.message} (Confidence: {(res.confidence_score * 100).toFixed(0)}%)
                      </Typography>
                    </Grid>
                  </Grid>
                </CardContent>
              </Card>
            ))
          )}
        </Grid>
      </Grid>
    </Box>
  )
}
