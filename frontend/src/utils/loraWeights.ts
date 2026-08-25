export const LORA_WEIGHT_MIN = -10
export const LORA_WEIGHT_MAX = 10

export function clampLoraWeight(weight: number): number {
  return Math.max(LORA_WEIGHT_MIN, Math.min(LORA_WEIGHT_MAX, weight))
}
