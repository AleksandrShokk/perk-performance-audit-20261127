import { type SupplyParameters, supplyParametersSchema } from '@app/schemas'

export const defaultSupplyParameters: SupplyParameters = {
  include_fbs: false,
  target_days: 30,
  lead_time_days: 7
}
export function readSupplyParameters(value: string | null): SupplyParameters {
  try {
    const result = supplyParametersSchema.safeParse(JSON.parse(value ?? '{}'))
    return result.success ? result.data : defaultSupplyParameters
  } catch {
    return defaultSupplyParameters
  }
}
