import { useState } from 'react'
import { Box, Skeleton } from '@mui/material'
import { ImageNotSupported } from '@mui/icons-material'

interface ProductThumbnailProps {
  sku: string
  size?: number
  onClick?: () => void
}

export default function ProductThumbnail({ sku, size = 40, onClick }: ProductThumbnailProps) {
  const [hasError, setHasError] = useState(false)
  const [isLoaded, setIsLoaded] = useState(false)

  const thumbnailUrl = `/api/v1/images/${sku}/thumbnail`

  if (hasError) {
    return (
      <Box
        sx={{
          width: size,
          height: size,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'grey.100',
          borderRadius: 0.5,
          color: 'grey.400',
          cursor: onClick ? 'pointer' : 'default',
        }}
        onClick={onClick}
      >
        <ImageNotSupported sx={{ fontSize: size * 0.5 }} />
      </Box>
    )
  }

  return (
    <Box
      sx={{
        width: size,
        height: size,
        position: 'relative',
        cursor: onClick ? 'pointer' : 'default',
        borderRadius: 0.5,
        overflow: 'hidden',
        flexShrink: 0,
      }}
      onClick={onClick}
    >
      {!isLoaded && (
        <Skeleton
          variant="rectangular"
          width={size}
          height={size}
          sx={{ position: 'absolute', top: 0, left: 0 }}
        />
      )}
      <Box
        component="img"
        src={thumbnailUrl}
        alt={sku}
        loading="lazy"
        onLoad={() => setIsLoaded(true)}
        onError={() => setHasError(true)}
        sx={{
          width: size,
          height: size,
          objectFit: 'cover',
          display: isLoaded ? 'block' : 'none',
          borderRadius: 0.5,
        }}
      />
    </Box>
  )
}
