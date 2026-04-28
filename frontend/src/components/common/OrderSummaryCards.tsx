import { Card, CardContent, Grid, Typography } from '@mui/material'

interface OrderSummaryCardsProps {
  totalOrders: number
  unmatchedOrders: number
  unmatchedItems: number
}

export default function OrderSummaryCards({
  totalOrders,
  unmatchedOrders,
  unmatchedItems,
}: OrderSummaryCardsProps) {
  return (
    <Grid container spacing={2} sx={{ mb: 3 }}>
      <Grid item xs={12} sm={4}>
        <Card>
          <CardContent sx={{ py: 1.5 }}>
            <Typography color="text.secondary" variant="body2">
              Total Orders
            </Typography>
            <Typography variant="h5">{totalOrders}</Typography>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} sm={4}>
        <Card>
          <CardContent sx={{ py: 1.5 }}>
            <Typography color="text.secondary" variant="body2">
              Unmatched Orders
            </Typography>
            <Typography variant="h5" color="warning.main">
              {unmatchedOrders}
            </Typography>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} sm={4}>
        <Card>
          <CardContent sx={{ py: 1.5 }}>
            <Typography color="text.secondary" variant="body2">
              Unmatched Items
            </Typography>
            <Typography variant="h5" color="error.main">
              {unmatchedItems}
            </Typography>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  )
}
