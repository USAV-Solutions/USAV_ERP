import { useState, useCallback, useRef } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  IconButton,
  ImageList,
  ImageListItem,
  ImageListItemBar,
  CircularProgress,
  Alert,
  LinearProgress,
} from '@mui/material'
import {
  Close,
  Delete,
  CloudUpload,
  ChevronLeft,
  ChevronRight,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axiosClient from '../../api/axiosClient'
import { IMAGES } from '../../api/endpoints'

interface SkuImagesResponse {
  sku: string
  listing: string
  total_images: number
  thumbnail_url: string
  images: { filename: string; url: string }[]
}

interface VariantImageDialogProps {
  open: boolean
  onClose: () => void
  sku: string
}

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10 MB

export default function VariantImageDialog({ open, onClose, sku }: VariantImageDialogProps) {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragActive, setDragActive] = useState(false)
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { data, isLoading, isError } = useQuery<SkuImagesResponse>({
    queryKey: ['sku-images', sku],
    queryFn: async () => {
      const response = await axiosClient.get(IMAGES.SKU_IMAGES(sku))
      return response.data
    },
    enabled: open && !!sku,
    retry: false,
  })

  const images = data?.images ?? []
  const listingName = data?.listing ?? 'listing-0'
  const listingIndex = parseInt(listingName.replace('listing-', ''), 10) || 0

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      const formData = new FormData()
      files.forEach((f) => formData.append('files', f))
      formData.append('listing_index', String(listingIndex))
      const response = await axiosClient.post(IMAGES.UPLOAD(sku), formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sku-images', sku] })
      queryClient.invalidateQueries({ queryKey: ['variants'] })
      setError(null)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Upload failed')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (filename: string) => {
      const response = await axiosClient.delete(
        IMAGES.DELETE_FILE(sku, listingIndex, filename),
      )
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sku-images', sku] })
      queryClient.invalidateQueries({ queryKey: ['variants'] })
      setPreviewIndex(null)
      setError(null)
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Delete failed')
    },
  })

  const validateAndUpload = useCallback(
    (fileList: FileList | File[]) => {
      const files = Array.from(fileList)
      const invalid = files.filter(
        (f) => !ACCEPTED_TYPES.includes(f.type) || f.size > MAX_FILE_SIZE,
      )
      if (invalid.length > 0) {
        setError(
          `Some files were rejected. Allowed: JPG, PNG, WEBP up to 10 MB each.`,
        )
        return
      }
      if (files.length > 0) {
        uploadMutation.mutate(files)
      }
    },
    [uploadMutation],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragActive(false)
      if (e.dataTransfer.files.length > 0) {
        validateAndUpload(e.dataTransfer.files)
      }
    },
    [validateAndUpload],
  )

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(true)
  }

  const handleDragLeave = () => setDragActive(false)

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndUpload(e.target.files)
      e.target.value = '' // reset so same file can be re-selected
    }
  }

  const handlePrev = () =>
    setPreviewIndex((i: number | null) => (i !== null && i > 0 ? i - 1 : images.length - 1))
  const handleNext = () =>
    setPreviewIndex((i: number | null) =>
      i !== null && i < images.length - 1 ? i + 1 : 0,
    )

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (previewIndex === null) return
    if (e.key === 'ArrowLeft') handlePrev()
    if (e.key === 'ArrowRight') handleNext()
    if (e.key === 'Escape') setPreviewIndex(null)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      onKeyDown={handleKeyDown}
    >
      <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="h6" component="span">
          Manage Images: {sku}
          {data && (
            <Typography variant="body2" component="span" sx={{ ml: 1, color: 'text.secondary' }}>
              ({data.total_images} image{data.total_images !== 1 ? 's' : ''})
            </Typography>
          )}
        </Typography>
        <IconButton onClick={onClose} size="small">
          <Close />
        </IconButton>
      </DialogTitle>

      <DialogContent>
        {error && (
          <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {uploadMutation.isPending && <LinearProgress sx={{ mb: 2 }} />}

        {/* Drop zone */}
        <Box
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          sx={{
            border: '2px dashed',
            borderColor: dragActive ? 'primary.main' : 'grey.400',
            borderRadius: 2,
            p: 3,
            mb: 2,
            textAlign: 'center',
            cursor: 'pointer',
            bgcolor: dragActive ? 'action.hover' : 'transparent',
            transition: 'all 0.2s',
            '&:hover': { borderColor: 'primary.main', bgcolor: 'action.hover' },
          }}
        >
          <CloudUpload sx={{ fontSize: 40, color: 'text.secondary', mb: 1 }} />
          <Typography variant="body1" color="text.secondary">
            Drag & drop images here, or click to browse
          </Typography>
          <Typography variant="caption" color="text.disabled">
            JPG, PNG, WEBP — up to 10 MB each
          </Typography>
          <input
            ref={fileInputRef}
            type="file"
            accept=".jpg,.jpeg,.png,.webp"
            multiple
            hidden
            onChange={handleFileSelect}
          />
        </Box>

        {/* Full-size preview */}
        {previewIndex !== null && images[previewIndex] && (
          <Box
            sx={{
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              bgcolor: 'grey.100',
              borderRadius: 1,
              mb: 2,
              minHeight: 400,
            }}
          >
            {images.length > 1 && (
              <IconButton
                onClick={handlePrev}
                sx={{
                  position: 'absolute',
                  left: 8,
                  bgcolor: 'rgba(255,255,255,0.8)',
                  '&:hover': { bgcolor: 'rgba(255,255,255,0.95)' },
                  zIndex: 1,
                }}
              >
                <ChevronLeft />
              </IconButton>
            )}
            <Box
              component="img"
              src={images[previewIndex].url}
              alt={images[previewIndex].filename}
              sx={{ maxWidth: '100%', maxHeight: 500, objectFit: 'contain' }}
            />
            {images.length > 1 && (
              <IconButton
                onClick={handleNext}
                sx={{
                  position: 'absolute',
                  right: 8,
                  bgcolor: 'rgba(255,255,255,0.8)',
                  '&:hover': { bgcolor: 'rgba(255,255,255,0.95)' },
                  zIndex: 1,
                }}
              >
                <ChevronRight />
              </IconButton>
            )}
          </Box>
        )}

        {/* Image grid */}
        {isLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        ) : isError || images.length === 0 ? (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <Typography color="text.secondary">
              {isError ? 'No images yet — upload some above.' : 'No images yet — upload some above.'}
            </Typography>
          </Box>
        ) : (
          <ImageList cols={4} gap={8}>
            {images.map((img: { filename: string; url: string }, idx: number) => (
              <ImageListItem
                key={img.filename}
                sx={{
                  cursor: 'pointer',
                  border: idx === previewIndex ? '3px solid' : '3px solid transparent',
                  borderColor: idx === previewIndex ? 'primary.main' : 'transparent',
                  borderRadius: 1,
                  overflow: 'hidden',
                  '&:hover .delete-btn': { opacity: 1 },
                }}
                onClick={() => setPreviewIndex(idx)}
              >
                <Box
                  component="img"
                  src={img.url}
                  alt={img.filename}
                  loading="lazy"
                  sx={{ width: '100%', height: 140, objectFit: 'cover' }}
                />
                <ImageListItemBar
                  sx={{ background: 'transparent' }}
                  position="top"
                  actionPosition="right"
                  actionIcon={
                    <IconButton
                      className="delete-btn"
                      size="small"
                      sx={{
                        color: 'white',
                        bgcolor: 'rgba(0,0,0,0.5)',
                        opacity: 0,
                        transition: 'opacity 0.2s',
                        m: 0.5,
                        '&:hover': { bgcolor: 'error.main' },
                      }}
                      onClick={(e: React.MouseEvent) => {
                        e.stopPropagation()
                        deleteMutation.mutate(img.filename)
                      }}
                    >
                      <Delete fontSize="small" />
                    </IconButton>
                  }
                />
              </ImageListItem>
            ))}
          </ImageList>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}
