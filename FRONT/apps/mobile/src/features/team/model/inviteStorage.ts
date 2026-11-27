import * as SecureStore from 'expo-secure-store'

const KEY = 'perk.pending-invite'
export const readInvite = () => SecureStore.getItemAsync(KEY)
export const saveInvite = (code: string) => SecureStore.setItemAsync(KEY, code)
export const deleteInvite = () => SecureStore.deleteItemAsync(KEY)
