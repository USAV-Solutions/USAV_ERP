import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  Typography,
} from '@mui/material'
import AddBusinessIcon from '@mui/icons-material/AddBusiness'
import LaunchIcon from '@mui/icons-material/Launch'
import axiosClient from '../api/axiosClient'
import { LISTINGS } from '../api/endpoints'

interface CreateListingPlatformCapability {
  platform: string
  enabled: boolean
  status: string
  notes: string
}

interface CreateListingScaffoldResponse {
  message: string
  supported_platforms: CreateListingPlatformCapability[]
}

export default function CreateProductListing() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['listing-create-scaffold'],
    queryFn: async () => {
      const response = await axiosClient.get<CreateListingScaffoldResponse>(LISTINGS.CREATE_SCAFFOLD)
      return response.data
    },
  })

  const ebayEnabled = data?.supported_platforms.find((item) => item.platform.startsWith('EBAY_') && item.enabled)

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 3 }}>
        <Typography variant="h4">Create New Listing</Typography>
        <Button variant="outlined" onClick={() => refetch()}>
          Refresh
        </Button>
      </Stack>

      <Alert severity="info" sx={{ mb: 3 }}>
        This section is scaffolded for new listing creation flows. eBay is the first target platform.
      </Alert>

      {isLoading ? (
        <Box sx={{ py: 6, display: 'flex', justifyContent: 'center' }}>
          <CircularProgress />
        </Box>
      ) : null}

      {isError ? (
        <Alert severity="error" sx={{ mb: 3 }}>
          Failed to load listing-create scaffold capabilities.
        </Alert>
      ) : null}

      {!isLoading && !isError ? (
        <Stack spacing={2}>
          {(data?.supported_platforms || []).map((item) => (
            <Card key={item.platform} variant="outlined">
              <CardContent>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'flex-start', sm: 'center' }} justifyContent="space-between">
                  <Box>
                    <Typography variant="h6">{item.platform}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {item.notes}
                    </Typography>
                  </Box>
                  <Chip label={item.status} color={item.enabled ? 'success' : 'default'} size="small" />
                </Stack>
              </CardContent>
            </Card>
          ))}

          <Card variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <AddBusinessIcon fontSize="small" />
                  <Typography variant="h6">eBay Listing Wizard (Scaffold)</Typography>
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  Start from this entry point to prepare and publish a new eBay listing. Full form workflow will be added next.
                </Typography>
                <Button
                  variant="contained"
                  startIcon={<LaunchIcon />}
                  disabled={!ebayEnabled}
                  onClick={() => {
                    // Scaffold action placeholder.
                  }}
                >
                  Start eBay Listing Flow
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      ) : null}
    </Box>
  )
}
