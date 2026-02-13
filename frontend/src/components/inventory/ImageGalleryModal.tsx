import { useState } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  IconButton,
  Box,
  ImageList,
  ImageListItem,
  Typography,
  CircularProgress,
} from '@mui/material'
import { Close, ChevronLeft, ChevronRight } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import axiosClient from '../../api/axiosClient'
import { IMAGES } from '../../api/endpoints'

interface SkuImagesResponse {
  sku: string
  listing: string
  total_images: number
  thumbnail_url: string
  images: { filename: string; url: string }[]
}

interface ImageGalleryModalProps {
  open: boolean
  onClose: () => void
  sku: string
}

export default function ImageGalleryModal({ open, onClose, sku }: ImageGalleryModalProps) {
  const [selectedIndex, setSelectedIndex] = useState(0)

  const { data, isLoading, isError } = useQuery<SkuImagesResponse>({
    queryKey: ['sku-images', sku],
    queryFn: async () => {
      const response = await axiosClient.get(IMAGES.SKU_IMAGES(sku))
      return response.data
    },
    enabled: open && !!sku,
  })

  const images = data?.images ?? []
  const selectedImage = images[selectedIndex]

  const handlePrev = () => {
    setSelectedIndex((prev) => (prev > 0 ? prev - 1 : images.length - 1))
  }

  const handleNext = () => {
    setSelectedIndex((prev) => (prev < images.length - 1 ? prev + 1 : 0))
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft') handlePrev()
    if (e.key === 'ArrowRight') handleNext()
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
          Images: {sku}
          {data && (
            <Typography variant="body2" component="span" sx={{ ml: 1, color: 'text.secondary' }}>
              ({data.listing} — {data.total_images} image{data.total_images !== 1 ? 's' : ''})
            </Typography>
          )}
        </Typography>
        <IconButton onClick={onClose} size="small">
          <Close />
        </IconButton>
      </DialogTitle>

      <DialogContent>
        {isLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
            <CircularProgress />
          </Box>
        ) : isError || images.length === 0 ? (
          <Box sx={{ textAlign: 'center', py: 8 }}>
            <Typography color="text.secondary">
              {isError ? 'Failed to load images' : 'No images available'}
            </Typography>
          </Box>
        ) : (
          <Box>
            {/* Main image viewer */}
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
                src={`/api/v1${selectedImage.url}`}
                alt={`${sku} - ${selectedImage.filename}`}
                sx={{
                  maxWidth: '100%',
                  maxHeight: 500,
                  objectFit: 'contain',
                }}
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

            {/* Image counter */}
            <Typography variant="body2" color="text.secondary" textAlign="center" sx={{ mb: 2 }}>
              {selectedIndex + 1} / {images.length}
            </Typography>

            {/* Thumbnail strip */}
            {images.length > 1 && (
              <ImageList cols={Math.min(images.length, 8)} gap={8} sx={{ mt: 1 }}>
                {images.map((img: { filename: string; url: string }, idx: number) => (
                  <ImageListItem
                    key={img.filename}
                    onClick={() => setSelectedIndex(idx)}
                    sx={{
                      cursor: 'pointer',
                      border: idx === selectedIndex ? '3px solid' : '3px solid transparent',
                      borderColor: idx === selectedIndex ? 'primary.main' : 'transparent',
                      borderRadius: 1,
                      overflow: 'hidden',
                      transition: 'border-color 0.2s',
                      '&:hover': {
                        borderColor: idx === selectedIndex ? 'primary.main' : 'grey.400',
                      },
                    }}
                  >
                    <Box
                      component="img"
                      src={`/api/v1${img.url}`}
                      alt={img.filename}
                      loading="lazy"
                      sx={{
                        width: '100%',
                        height: 80,
                        objectFit: 'cover',
                      }}
                    />
                  </ImageListItem>
                ))}
              </ImageList>
            )}
          </Box>
        )}
      </DialogContent>
    </Dialog>
  )
}
