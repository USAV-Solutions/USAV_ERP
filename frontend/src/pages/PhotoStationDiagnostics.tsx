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
  IconButton,
  Breadcrumbs,
  Link as MuiLink,
} from '@mui/material'
import {
  CloudUpload,
  AutoAwesome,
  CheckCircle,
  Error as ErrorIcon,
  Warning,
  Speed,
  FolderSpecial,
  FindInPage,
  Inventory,
  Refresh,
} from '@mui/icons-material'
import axiosClient from '../api/axiosClient'

interface DiagnosticResult {
  success: bool
  filename: string
  latency_ms: number
  is_valid_packing_photo: boolean
  platform: string
  order_id: string
  tracking_number: str
  sku_on_slip?: string
  detected_physical_item: string
  expected_erp_item?: string
  item_match: boolean
  confidence_score: number
  status: 'CORRECT' | 'MISSING_TRACKING' | 'ORDER_NOT_IN_ERP' | 'NO_PACKING_SLIP' | 'ERROR'
  message: string
  previewUrl?: string
}

export default function PhotoStationDiagnostics() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [isDiagnosing, setIsDiagnosing] = useState(false)
  const [resultsHistory, setResultsHistory] = useState<DiagnosticResult[]>([])
  const [activeTab, setActiveTab] = useState<'sandbox' | 'nas_samples'>('sandbox')

  // Sample pre-configured NAS folder path from Synology NAS
  const nasFolderPath = "USAV Media > Packing Shipping > Packing Photos > Packing Station 2 > 2026 > Q2 26"

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
        previewUrl: previewUrl || undefined,
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
        return <Chip icon={<Warning />} label="ORDER NOT IN ERP" color="warning" sx={{ fontWeight: 'bold' }} />
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
          SYNOLOGY NAS FOLDER TARGET
        </Typography>
        <Breadcrumbs separator="›" aria-label="breadcrumb" sx={{ mt: 0.5 }}>
          {nasFolderPath.split(' > ').map((folder, idx) => (
            <Typography key={idx} variant="body2" color={idx === 5 ? 'primary.main' : 'text.primary'} fontWeight={idx === 5 ? 'bold' : 'normal'}>
              {folder}
            </Typography>
          ))}
        </Breadcrumbs>
      </Paper>

      {/* Main Sandbox Card */}
      <Grid container spacing={3}>
        <Grid item xs={12} md={5}>
          <Card elevation={2} sx={{ borderRadius: 2 }}>
            <CardContent>
              <Typography variant="h6" fontWeight="bold" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                <AutoAwesome color="primary" /> AI Diagnostic Sandbox
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
                  <CloudUpload color="primary" sx={{ fontSize: 48, mb: 1 }} />
                  <Typography variant="subtitle1" fontWeight="bold">
                    {selectedFile ? selectedFile.name : 'Choose Sample Photo or Drag & Drop'}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Supports JPG, PNG, WEBP from NAS or Local Drive
                  </Typography>
                </label>
              </Box>

              {/* Selected Image Preview */}
              {previewUrl && (
                <Box sx={{ mt: 2, textAlign: 'center' }}>
                  <img
                    src={previewUrl}
                    alt="Preview"
                    style={{ width: '100%', maxHeight: 220, objectFit: 'contain', borderRadius: 8, border: '1px solid #e0e0e0' }}
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
                {isDiagnosing ? <CircularProgress size={24} color="inherit" /> : 'RUN GEMINI 3.5 FLASH DIAGNOSIS'}
              </Button>
            </CardContent>
          </Card>
        </Grid>

        {/* Diagnostic Results History Panel */}
        <Grid item xs={12} md={7}>
          <Typography variant="h6" fontWeight="bold" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
            <FindInPage color="primary" /> Diagnostic Inspection Results ({resultsHistory.length})
          </Typography>

          {resultsHistory.length === 0 ? (
            <Paper elevation={1} sx={{ p: 4, textAlign: 'center', borderRadius: 2 }}>
              <Inventory sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
              <Typography variant="body1" color="text.secondary">
                No diagnostic runs yet. Select a sample photo from the NAS folder to run AI verification.
              </Typography>
            </Paper>
          ) : (
            resultsHistory.map((res, index) => (
              <Card key={index} elevation={2} sx={{ mb: 2, borderRadius: 2 }}>
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

                  <Divider sx={{ my: 1 }} />

                  <Grid container spacing={2}>
                    <Grid item xs={12} sm={4}>
                      {res.previewUrl && (
                        <img
                          src={res.previewUrl}
                          alt="Thumbnail"
                          style={{ width: '100%', height: 110, objectFit: 'cover', borderRadius: 6 }}
                        />
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

                      <Box sx={{ mt: 1, p: 1, bgcolor: 'background.default', borderRadius: 1 }}>
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

                  <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
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
