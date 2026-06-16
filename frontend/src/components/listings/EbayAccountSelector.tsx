import React from 'react'
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import { getEbayAccounts } from '../../api/ebayListing'
import { EbayAccountInfo } from '../../types/ebayListing'

interface EbayAccountSelectorProps {
  value: string
  onChange: (storeId: string) => void
  onAccountsLoaded?: (accounts: EbayAccountInfo[]) => void
}

export default function EbayAccountSelector({ value, onChange, onAccountsLoaded }: EbayAccountSelectorProps) {
  const { data: accounts = [], isLoading, isError } = useQuery({
    queryKey: ['ebay-accounts'],
    queryFn: async () => {
      const data = await getEbayAccounts()
      if (onAccountsLoaded) {
        onAccountsLoaded(data)
      }
      return data
    },
    staleTime: 60000 * 5, // 5 minutes
  })

  if (isLoading) {
    return <CircularProgress size={24} />
  }

  if (isError) {
    return <Typography color="error">Failed to load eBay accounts</Typography>
  }

  return (
    <FormControl fullWidth size="small">
      <InputLabel>eBay Store Account *</InputLabel>
      <Select
        value={value}
        label="eBay Store Account *"
        onChange={(e) => onChange(e.target.value as string)}
      >
        {accounts.map((acc) => (
          <MenuItem key={acc.id} value={acc.id}>
            {acc.name}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  )
}
