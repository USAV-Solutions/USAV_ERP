import React, { useState } from 'react'
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
  TextField,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
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
  const [isNasLoading, setIsNasLoading] = useState(false)
  const [nasLimit, setNasLimit] = useState<number>(5)
  const [resultsHistory, setResultsHistory] = useState<DiagnosticResult[]>([])
  const [nasError, setNasError] = useState<string | null>(null)

  // Default target path on Synology NAS
  const nasFolderPath = '/USAV Media/Packing Shipping/Packing Photos/Packing Station 2/2026/Q2 26'

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

  const runDiagnosis = async () => {
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

  const runNasBatchDiagnosis = async () => {
    setIsNasLoading(true)
    setNasError(null)

    try {
      const res = await axiosClient.post('/orders/photo-station/diagnose-nas', {
        folder_path: nasFolderPath,
        limit: nasLimit,
      })

      const batchResults: DiagnosticResult[] = res.data.map((item: any) => ({
        ...item,
        previewUrl: item.image_data_url || undefined,
      }))

      setResultsHistory((prev) => [...batchResults, ...prev])
    } catch (err: any) {
      console.error('NAS Batch diagnosis failed:', err)
      setNasError(err?.response?.data?.detail || 'Failed to fetch photos from Synology NAS via QuickConnect.')
    } finally {
      setIsNasLoading(false)
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
      {/* Breadcrumb Header */}
      <Paper elevation={0} sx={{ p: 2, mb: 3, bgcolor: 'background.paper', borderRadius: 2 }}>
        <Typography variant="caption" color="text.secondary" fontWeight="bold">
          SYNOLOGY NAS QUICKCONNECT TARGET
        </Typography>
        <Breadcrumbs separator="›" aria-label="breadcrumb" sx={{ mt: 0.5 }}>
          <Typography variant="body2" color="primary.main" fontWeight="bold">
            USAV Media
          </Typography>
          <Typography variant="body2">Packing Shipping</Typography>
          <Typography variant="body2">Packing Photos</Typography>
          <Typography variant="body2">Packing Station 2</Typography>
          <Typography variant="body2">2026</Typography>
          <Typography variant="body2" color="primary.main" fontWeight="bold">
            Q2 26
          </Typography>
        </Breadcrumbs>
      </Paper>

      {/* Main Grid */}
      <Grid container spacing={3}>
        <Grid item xs={12} md={5}>
          {/* NAS Direct Fetch Card */}
          <Card elevation={3} sx={{ borderRadius: 2, mb: 3, border: '1px solid #e0e0e0' }}>
            <CardContent>
              <Typography variant="h6" fontWeight="bold" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                <Dns color="primary" /> Stream NAS Batch (QuickConnect)
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                Stream sample photos directly from Synology NAS over QuickConnect WebAPI and analyze with Gemini 3.5 Flash.
              </Typography>

              <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
                <FormControl fullWidth size="small">
                  <InputLabel>Max Photos Limit</InputLabel>
                  <Select
                    value={nasLimit}
                    label="Max Photos Limit"
                    onChange={(e) => setNasLimit(Number(e.target.value))}
                  >
                    <MenuItem value={3}>3 Sample Photos</MenuItem>
                    <MenuItem value={5}>5 Sample Photos</MenuItem>
                    <MenuItem value={10}>10 Sample Photos</MenuItem>
                    <MenuItem value={20}>20 Sample Photos</MenuItem>
                  </Select>
                </FormControl>
              </Box>

              <Button
                fullWidth
                variant="contained"
                color="secondary"
                size="large"
                disabled={isNasLoading}
                onClick={runNasBatchDiagnosis}
                startIcon={isNasLoading ? <CircularProgress size={20} color="inherit" /> : <Dns />}
                sx={{ py: 1.4, fontWeight: 'bold' }}
              >
                {isNasLoading ? 'STREAMING NAS PHOTOS & DIAGNOSING...' : 'RUN NAS BATCH TEST VIA QUICKCONNECT'}
              </Button>

              {nasError && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {nasError}
                </Alert>
              )}
            </CardContent>
          </Card>

          {/* Local File Upload Card */}
          <Card elevation={2} sx={{ borderRadius: 2 }}>
            <CardContent>
              <Typography variant="h6" fontWeight="bold" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                <AutoAwesome color="primary" /> Single Photo Sandbox
              </Typography>

              {/* Drag and Drop Zone */}
              <Box
                onDragOver={(e) => e.preventDefault()}
                onDrop={handleDrop}
                sx={{
                  border: '2px dashed',
                  borderColor: selectedFile ? 'primary.main' : 'grey.400',
                  borderRadius: 2,
                  p: 3,
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
                  <CloudUpload color="primary" sx={{ fontSize: 44, mb: 1 }} />
                  <Typography variant="subtitle1" fontWeight="bold">
                    {selectedFile ? selectedFile.name : 'Choose Local Photo or Drag & Drop'}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Supports JPG, PNG, WEBP
                  </Typography>
                </label>
              </Box>

              {/* Selected Image Preview */}
              {previewUrl && (
                <Box sx={{ mt: 2, textAlign: 'center' }}>
                  <img
                    src={previewUrl}
                    alt="Preview"
                    style={{ width: '100%', maxHeight: 200, objectFit: 'contain', borderRadius: 8, border: '1px solid #e0e0e0' }}
                  />
                </Box>
              )}

              <Button
                fullWidth
                variant="contained"
                color="primary"
                size="large"
                disabled={!selectedFile || isDiagnosing}
                onClick={runDiagnosis}
                startIcon={<AutoAwesome />}
                sx={{ mt: 2.5, py: 1.4, fontWeight: 'bold' }}
              >
                {isDiagnosing ? <CircularProgress size={24} color="inherit" /> : 'DIAGNOSE SELECTED PHOTO'}
              </Button>
            </CardContent>
          </Card>
        </Grid>

        {/* Diagnostic Results History Panel */}
        <Grid item xs={12} md={7}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6" fontWeight="bold" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <FindInPage color="primary" /> Diagnostic Inspection Results ({resultsHistory.length})
            </Typography>
            {resultsHistory.length > 0 && (
              <Button size="small" variant="outlined" startIcon={<Refresh />} onClick={() => setResultsHistory([])}>
                Clear Results
              </Button>
            )}
          </Box>

          {resultsHistory.length === 0 ? (
            <Paper elevation={1} sx={{ p: 5, textAlign: 'center', borderRadius: 2, bgcolor: 'background.paper' }}>
              <Inventory sx={{ fontSize: 56, color: 'text.secondary', mb: 1.5 }} />
              <Typography variant="h6" fontWeight="bold" color="text.primary" sx={{ mb: 1 }}>
                No diagnostic runs yet
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 460, mx: 'auto', mb: 3 }}>
                Click <strong>"RUN NAS BATCH TEST VIA QUICKCONNECT"</strong> to stream historical packing photos directly from your Synology NAS, or upload a photo to analyze.
              </Typography>
              <Button
                variant="contained"
                color="secondary"
                startIcon={<Dns />}
                onClick={runNasBatchDiagnosis}
                disabled={isNasLoading}
                sx={{ fontWeight: 'bold' }}
              >
                STREAM & DIAGNOSE NAS PHOTOS NOW
              </Button>
            </Paper>
          ) : (
            resultsHistory.map((res, index) => (
              <Card key={index} elevation={2} sx={{ mb: 2.5, borderRadius: 2, overflow: 'hidden' }}>
                <CardContent>
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
                          alt="Packaging Photo"
                          style={{ width: '100%', height: 130, objectFit: 'cover', borderRadius: 6, border: '1px solid #e0e0e0' }}
                        />
                      ) : (
                        <Box sx={{ height: 130, bgcolor: 'action.hover', borderRadius: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Inventory color="disabled" />
                        </Box>
                      )}
                    </Grid>
                    <Grid item xs={12} sm={8}>
                      <Typography variant="body2" color="text.secondary">
                        Platform: <strong>{res.platform}</strong> | Order ID: <strong>{res.order_id || 'N/A'}</strong>
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Tracking Number: <strong>{res.tracking_number || 'N/A'}</strong>
                      </Typography>
                      {res.sku_on_slip && (
                        <Typography variant="body2" color="text.secondary">
                          SKU on Slip: <strong>{res.sku_on_slip}</strong>
                        </Typography>
                      )}

                      <Box sx={{ mt: 1.5, p: 1.2, bgcolor: 'background.default', borderRadius: 1.5, border: '1px solid #e0e0e0' }}>
                        <Typography variant="caption" color="primary.main" fontWeight="bold" display="block">
                          AI DETECTED PHYSICAL ITEM:
                        </Typography>
                        <Typography variant="body2" fontWeight="medium">
                          {res.detected_physical_item}
                        </Typography>
                        {res.expected_erp_item && (
                          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                            ERP Expected Item: <strong>{res.expected_erp_item}</strong>
                          </Typography>
                        )}
                      </Box>
                    </Grid>
                  </Grid>

                  <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: 'block' }}>
                    {res.message} (Confidence: {(res.confidence_score * 100).toFixed(0)}%)
                  </Typography>
                </CardContent>
              </Card>
            ))
          )}
        </Grid>
      </Grid>
    </Box>
  )
}
