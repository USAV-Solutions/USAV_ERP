import React, { useState, useRef } from 'react'
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
  SkipNext,
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
  const [currentOffset, setCurrentOffset] = useState<number>(0)
  const [totalInFolder, setTotalInFolder] = useState<number>(0)
  const [resultsHistory, setResultsHistory] = useState<DiagnosticResult[]>([])
  const [nasError, setNasError] = useState<string | null>(null)

  const isStreamingRef = useRef(false)
  const activeStreamIdRef = useRef<number>(0)
  const processedFilesSet = useRef<Set<string>>(new Set())

  const nasFolderPath = '/USAV Media/Packing Shipping/Packing Photos/Packing Station 2/2026/Q2 26'

  // NO AUTO-STREAMING ON MOUNT. All stream operations are 100% manual user clicks.

  const clearAllCacheAndState = async () => {
    setResultsHistory([])
    setCurrentOffset(0)
    processedFilesSet.current.clear()
    try {
      await axiosClient.post('/orders/photo-station/clear-cache')
      console.log('[NAS Stream] Diagnostic cache cleared successfully.')
    } catch (e) {
      console.warn('[NAS Stream] Failed to clear backend cache:', e)
    }
  }

  const startNasStream = async (offset: number = 0, limit: number = nasLimit, resetHistory: boolean = false) => {
    const streamId = Date.now()
    console.log(`[NAS Stream Start] Session ID=${streamId} | Offset=${offset} | Limit=${limit} | ResetHistory=${resetHistory}`)

    activeStreamIdRef.current = streamId
    isStreamingRef.current = true
    setIsStreaming(true)
    setNasError(null)

    if (resetHistory) {
      await clearAllCacheAndState()
    }

    try {
      console.log(`[NAS Stream] Fetching NAS file list with offset=${offset}, limit=${limit}...`)
      const listRes = await axiosClient.get('/orders/photo-station/nas-files', {
        params: { folder_path: nasFolderPath, offset: offset, limit: limit }
      })

      if (activeStreamIdRef.current !== streamId) {
        console.warn(`[NAS Stream] Session ${streamId} cancelled after file list fetch.`)
        return
      }

      const filePaths: string[] = listRes.data.files || []
      console.log(`[NAS Stream] NAS returned ${filePaths.length} files:`, filePaths)
      setTotalInFolder(listRes.data.total_in_folder || 0)

      if (filePaths.length === 0) {
        setNasError(`No more images found in NAS folder beyond offset ${offset}.`)
        setIsStreaming(false)
        isStreamingRef.current = false
        return
      }

      setStreamProgress({ current: 0, total: filePaths.length, filename: 'Initializing stream...' })

      for (let i = 0; i < filePaths.length; i++) {
        if (activeStreamIdRef.current !== streamId) {
          console.warn(`[NAS Stream] Session ${streamId} superseded at loop index ${i}, stopping.`)
          return
        }

        const filePath = filePaths[i]
        const filename = filePath.split('/').pop() || filePath

        if (processedFilesSet.current.has(filePath)) {
          console.warn(`[NAS Stream] File ${filePath} already processed in this stream session, skipping.`)
          continue
        }
        processedFilesSet.current.add(filePath)

        console.log(`[NAS Stream] [Session ${streamId}] [${i + 1}/${filePaths.length}] Diagnosing file: ${filePath}`)
        setStreamProgress({ current: i + 1, total: filePaths.length, filename: filename })

        try {
          const diagRes = await axiosClient.post('/orders/photo-station/diagnose-nas-file', {
            file_path: filePath
          })

          if (activeStreamIdRef.current !== streamId) {
            console.warn(`[NAS Stream] Session ${streamId} cancelled after HTTP POST for ${filename}.`)
            return
          }

          const data: DiagnosticResult = {
            ...diagRes.data,
            previewUrl: diagRes.data.image_data_url || undefined
          }

          console.log(`[NAS Stream API Success] ${filename} -> Order: ${data.order_id}, Item: "${data.detected_physical_item}"`)

          // Strict filtering deduplication by filename
          setResultsHistory((prev) => {
            const filtered = prev.filter((item) => item.filename !== data.filename)
            return [data, ...filtered]
          })
        } catch (err: any) {
          console.error(`[NAS Stream Error] Failed to diagnose ${filename}:`, err)
        }
      }

      if (activeStreamIdRef.current === streamId) {
        setCurrentOffset(offset + filePaths.length)
        console.log(`[NAS Stream Complete] Session ${streamId} finished. Next offset: ${offset + filePaths.length}`)
      }
    } catch (err: any) {
      console.error('[NAS Stream Error] Failed to list NAS files:', err)
      setNasError(err?.response?.data?.detail || 'Failed to connect to Synology NAS over QuickConnect.')
    } finally {
      if (activeStreamIdRef.current === streamId) {
        setIsStreaming(false)
        isStreamingRef.current = false
      }
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

      setResultsHistory((prev) => {
        const filtered = prev.filter((item) => item.filename !== data.filename)
        return [data, ...filtered]
      })
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
                <Chip label={`PROCESSED ${resultsHistory.length} / ${totalInFolder || '?'} NAS PHOTOS`} color="success" size="small" variant="outlined" sx={{ fontWeight: 'bold' }} />
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
            <FormControl size="small" sx={{ minWidth: 130 }}>
              <InputLabel>Batch Size</InputLabel>
              <Select
                value={nasLimit}
                label="Batch Size"
                onChange={(e) => setNasLimit(Number(e.target.value))}
              >
                <MenuItem value={3}>3 Photos</MenuItem>
                <MenuItem value={5}>5 Photos</MenuItem>
                <MenuItem value={10}>10 Photos</MenuItem>
                <MenuItem value={20}>20 Photos</MenuItem>
              </Select>
            </FormControl>

            <Button
              variant="outlined"
              color="primary"
              disabled={isStreaming}
              startIcon={<Refresh />}
              onClick={() => startNasStream(0, nasLimit, true)}
              sx={{ fontWeight: 'bold', py: 1 }}
            >
              RE-STREAM FROM START
            </Button>

            <Button
              variant="contained"
              color="primary"
              disabled={isStreaming}
              startIcon={isStreaming ? <CircularProgress size={18} color="inherit" /> : <SkipNext />}
              onClick={() => startNasStream(currentOffset, nasLimit, false)}
              sx={{ fontWeight: 'bold', py: 1 }}
            >
              {isStreaming ? 'STREAMING...' : `STREAM NEXT ${nasLimit} PHOTOS`}
            </Button>
          </Box>
        </Box>

        {/* Live Streaming Progress Bar */}
        {isStreaming && (
          <Box sx={{ mt: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="caption" color="primary.main" fontWeight="bold">
                Streaming Photo {streamProgress.current} of {streamProgress.total}: {streamProgress.filename} (Offset: {currentOffset})
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
              <FindInPage color="primary" /> Live Diagnostic Cards ({resultsHistory.length})
            </Typography>
            {resultsHistory.length > 0 && (
              <Button size="small" variant="outlined" startIcon={<Refresh />} onClick={clearAllCacheAndState}>
                Clear All Cards
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
                Click <strong>"START LIVE STREAM NOW"</strong> or <strong>"RE-STREAM FROM START"</strong> to stream packaging photos from your Synology NAS over QuickConnect.
              </Typography>
              <Button
                variant="contained"
                color="primary"
                startIcon={<PlayArrow />}
                onClick={() => startNasStream(0, nasLimit, true)}
                sx={{ fontWeight: 'bold' }}
              >
                START LIVE STREAM NOW
              </Button>
            </Paper>
          ) : (
            resultsHistory.map((res, index) => (
              <Card key={res.filename || index} elevation={2} sx={{ mb: 2.5, borderRadius: 2, overflow: 'hidden', transition: 'all 0.3s' }}>
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
