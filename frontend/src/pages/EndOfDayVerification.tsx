import React, { useState } from 'react'
import {
  Box,
  Typography,
  Paper,
  Button,
  TextField,
  Alert,
  CircularProgress,
  Card,
  CardContent,
} from '@mui/material'
import { LocalShipping, CheckCircle, Error as ErrorIcon, CameraAlt } from '@mui/icons-material'
import axiosClient from '../api/axiosClient'

export default function EndOfDayVerification() {
  const [manualCount, setManualCount] = useState<string>('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [result, setResult] = useState<{
    success: boolean
    box_count: number
    verified_orders_count: number
    mismatch: boolean
    message: string
  } | null>(null)

  const handleSubmit = async () => {
    setIsSubmitting(true)
    setResult(null)

    try {
      const payload = {
        photo_path: '/volume1/photo/shelf_end_of_day.jpg',
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
    <Box sx={{ p: { xs: 1, md: 3 }, maxWidth: 800, mx: 'auto' }}>
      <Paper
        elevation={0}
        sx={{
          p: 2.5,
          mb: 3,
          bgcolor: 'primary.main',
          color: 'white',
          borderRadius: 2,
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
        }}
      >
        <LocalShipping sx={{ fontSize: 32 }} />
        <Box>
          <Typography variant="h5" fontWeight="bold">
            End-of-Day Shelf Verification
          </Typography>
          <Typography variant="body2" sx={{ opacity: 0.9 }}>
            Cross-check physical shelf box count against verified ERP orders before carrier dispatch.
          </Typography>
        </Box>
      </Paper>

      {result && (
        <Paper
          elevation={3}
          sx={{
            p: 3,
            mb: 3,
            borderRadius: 2,
            bgcolor: result.success ? '#2e7d32' : '#d32f2f',
            color: 'white',
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
            {result.success ? <CheckCircle sx={{ fontSize: 40 }} /> : <ErrorIcon sx={{ fontSize: 40 }} />}
            <Typography variant="h5" fontWeight="bold">
              {result.success ? 'SHELF COUNT MATCHED - READY TO SHIP' : 'COUNT MISMATCH WARNING'}
            </Typography>
          </Box>
          <Typography variant="body1" sx={{ mt: 1 }}>
            {result.message}
          </Typography>
          <Box sx={{ mt: 2, display: 'flex', gap: 3 }}>
            <Typography variant="subtitle2">
              Physical Box Count: <strong>{result.box_count}</strong>
            </Typography>
            <Typography variant="subtitle2">
              Verified Orders: <strong>{result.verified_orders_count}</strong>
            </Typography>
          </Box>
        </Paper>
      )}

      <Card elevation={2} sx={{ borderRadius: 2 }}>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h6" fontWeight="bold" sx={{ mb: 2 }}>
            Run Shelf Audit
          </Typography>

          <TextField
            fullWidth
            type="number"
            label="Manual Shelf Box Count (Optional)"
            placeholder="Enter physical box count on shelf..."
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
            sx={{ py: 1.5, fontSize: '1.1rem', fontWeight: 'bold' }}
          >
            {isSubmitting ? <CircularProgress size={24} color="inherit" /> : 'RUN END-OF-DAY SHELF VERIFICATION'}
          </Button>
        </CardContent>
      </Card>
    </Box>
  )
}
