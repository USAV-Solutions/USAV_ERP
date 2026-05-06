import { useMemo, useState, type DragEvent } from 'react'
import axios from 'axios'
import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Stack,
  Typography,
} from '@mui/material'

import axiosClient from '../../api/axiosClient'
import sampleBoaV1Pdf from '../../assets/samples/sample_BoA.pdf'
import sampleBoaV2Pdf from '../../assets/samples/sample_BoA2.pdf'
import sampleBoaV3Pdf from '../../assets/samples/sample_BoA3.pdf'
import sampleAmazonPdf from '../../assets/samples/sample_amazon.pdf'
import sampleApplePdf from '../../assets/samples/sample_apple.pdf'
import sampleChasePdf from '../../assets/samples/sample_chase.pdf'

type OutputType = 'csv' | 'xlsx'

interface FormatOption {
  id: string
  label: string
  samplePdfPath: string
  description: string
}

const FORMAT_OPTIONS: FormatOption[] = [
  { id: 'boa_v1', label: 'BoA Format 1', samplePdfPath: sampleBoaV1Pdf, description: 'BoA posting/transaction date style.' },
  { id: 'boa_v2', label: 'BoA Format 2', samplePdfPath: sampleBoaV2Pdf, description: 'BoA account/category ledger style.' },
  { id: 'boa_v3', label: 'BoA Format 3', samplePdfPath: sampleBoaV3Pdf, description: 'BoA online banking export style.' },
  { id: 'amazon', label: 'Amazon Statement', samplePdfPath: sampleAmazonPdf, description: 'Amazon settlement statement format.' },
  { id: 'apple', label: 'Apple Card', samplePdfPath: sampleApplePdf, description: 'Apple Card statement format.' },
  { id: 'chase', label: 'Chase Statement', samplePdfPath: sampleChasePdf, description: 'Chase account activity section format.' },
]

function extractFilename(contentDisposition: string | undefined, fallback: string): string {
  if (!contentDisposition) return fallback
  const match = contentDisposition.match(/filename="?([^";]+)"?/i)
  return match?.[1] || fallback
}

export default function BankConversion() {
  const [selectedFormat, setSelectedFormat] = useState<string>('boa_v1')
  const [outputType, setOutputType] = useState<OutputType>('xlsx')
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [isConverting, setIsConverting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [sampleDialog, setSampleDialog] = useState<FormatOption | null>(null)

  const selectedFormatMeta = useMemo(
    () => FORMAT_OPTIONS.find((option) => option.id === selectedFormat),
    [selectedFormat],
  )

  const setSelectedPdf = (nextFile: File | null) => {
    if (!nextFile) {
      setFile(null)
      return
    }
    if (!nextFile.name.toLowerCase().endsWith('.pdf')) {
      setError('Please upload a PDF file.')
      return
    }
    setError(null)
    setFile(nextFile)
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
    const dropped = event.dataTransfer.files?.[0] ?? null
    setSelectedPdf(dropped)
  }

  const downloadConvertedFile = async () => {
    if (!file) {
      setError('Please choose a PDF file before converting.')
      return
    }
    if (!selectedFormat) {
      setError('Please select a bank format.')
      return
    }

    setError(null)
    setIsConverting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('format_type', selectedFormat)
      formData.append('output_type', outputType)

      const response = await axiosClient.post('/accounting/bank-convert', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        responseType: 'blob',
      })

      const defaultFilename = `bank_convert.${outputType}`
      const filename = extractFilename(response.headers['content-disposition'], defaultFilename)
      const blobUrl = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = blobUrl
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(blobUrl)
      setSuccessMessage(`Converted and downloaded: ${filename}`)
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const status = requestError.response?.status
        if (status === 400) {
          setError('Format does not match selected bank')
        } else if (status === 501) {
          setError('Selected format is not implemented yet')
        } else {
          setError('Failed to convert file. Please try again.')
        }
      } else {
        setError('Failed to convert file. Please try again.')
      }
    } finally {
      setIsConverting(false)
    }
  }

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h4" gutterBottom>
          Bank Statement Conversion
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Upload PDF bank statements and convert to CSV or XLSX.
        </Typography>
      </Box>

      {error ? <Alert severity="error">{error}</Alert> : null}

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            1. Select Bank Format
          </Typography>
          <Grid container spacing={2}>
            {FORMAT_OPTIONS.map((option) => (
              <Grid item xs={12} md={6} lg={4} key={option.id}>
                <Card
                  variant={selectedFormat === option.id ? 'elevation' : 'outlined'}
                  sx={{ borderWidth: selectedFormat === option.id ? 2 : 1, borderStyle: 'solid', borderColor: selectedFormat === option.id ? 'primary.main' : 'divider' }}
                >
                  <CardContent>
                    <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                      <Typography variant="subtitle1">{option.label}</Typography>
                      {selectedFormat === option.id ? <Chip size="small" color="primary" label="Selected" /> : null}
                    </Stack>
                    <Typography variant="body2" color="text.secondary">
                      {option.description}
                    </Typography>
                  </CardContent>
                  <CardActions sx={{ justifyContent: 'space-between' }}>
                    <Button size="small" onClick={() => setSampleDialog(option)}>
                      View Sample
                    </Button>
                    <Button size="small" variant="contained" onClick={() => setSelectedFormat(option.id)}>
                      Choose
                    </Button>
                  </CardActions>
                </Card>
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            2. Upload PDF
          </Typography>
          <Box
            onDragOver={(event) => {
              event.preventDefault()
              setIsDragging(true)
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={onDrop}
            sx={{
              p: 4,
              border: '2px dashed',
              borderColor: isDragging ? 'primary.main' : 'divider',
              borderRadius: 2,
              textAlign: 'center',
              backgroundColor: isDragging ? 'action.hover' : 'transparent',
            }}
          >
            <Typography variant="body1" mb={2}>
              Drag and drop PDF here, or choose file
            </Typography>
            <Button component="label" variant="outlined">
              Select PDF File
              <input
                hidden
                type="file"
                accept="application/pdf,.pdf"
                onChange={(event) => setSelectedPdf(event.target.files?.[0] ?? null)}
              />
            </Button>
            <Typography variant="body2" color="text.secondary" mt={2}>
              {file ? `Selected: ${file.name}` : 'No file selected'}
            </Typography>
          </Box>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            3. Convert & Download
          </Typography>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'stretch', sm: 'center' }}>
            <FormControl sx={{ minWidth: 180 }}>
              <InputLabel id="output-type-label">Output</InputLabel>
              <Select
                labelId="output-type-label"
                value={outputType}
                label="Output"
                onChange={(event) => setOutputType(event.target.value as OutputType)}
              >
                <MenuItem value="xlsx">Excel (.xlsx)</MenuItem>
                <MenuItem value="csv">CSV (.csv)</MenuItem>
              </Select>
            </FormControl>
            <Button
              variant="contained"
              size="large"
              onClick={downloadConvertedFile}
              disabled={!file || !selectedFormat || selectedFormat === 'format_7' || isConverting}
            >
              {isConverting ? 'Converting...' : 'Convert & Download'}
            </Button>
            {selectedFormatMeta ? (
              <Typography variant="body2" color="text.secondary">
                Active format: {selectedFormatMeta.label}
              </Typography>
            ) : null}
            {selectedFormat === 'format_7' ? (
              <Typography variant="body2" color="warning.main">
                Format 7 placeholder only. Choose one of first 6 formats to convert.
              </Typography>
            ) : null}
          </Stack>
        </CardContent>
      </Card>

      <Dialog open={Boolean(sampleDialog)} onClose={() => setSampleDialog(null)} maxWidth="md" fullWidth>
        <DialogTitle>{sampleDialog?.label} Sample</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" mb={2}>
            Sample PDF: {sampleDialog?.samplePdfPath}
          </Typography>
          <Box
            component="iframe"
            src={sampleDialog?.samplePdfPath}
            title={`${sampleDialog?.label ?? 'Format'} sample`}
            sx={{ width: '100%', height: 620, borderRadius: 1, border: '1px solid', borderColor: 'divider' }}
          />
        </DialogContent>
      </Dialog>

      <Snackbar
        open={Boolean(successMessage)}
        autoHideDuration={2500}
        onClose={() => setSuccessMessage(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity="success" onClose={() => setSuccessMessage(null)} sx={{ width: '100%' }}>
          {successMessage}
        </Alert>
      </Snackbar>
    </Stack>
  )
}
