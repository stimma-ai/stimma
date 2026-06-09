/**
 * Shared filter definitions for in-app (built-in) image filters.
 *
 * Single source of truth consumed by:
 * - the editor's filter/finetune plugins (matrices/ranges),
 * - the ToolView post-processing chain step cards (param UI),
 * - the backend server-side port (backend/postprocessing/filter_defs.py mirrors
 *   this file; a parity test asserts ids/params/ranges match).
 *
 * Keep this file declarative — ids, labels, params, ranges, defaults. The
 * actual pixel math lives in utils/colorMatrix.ts (client) and
 * backend/postprocessing/builtin_filters.py (server).
 */

import { FILTER_CATEGORIES, FILTER_MATRICES } from './constants';

export interface ChainFilterParam {
  name: string;
  label: string;
  type: 'number' | 'integer' | 'enum';
  default: number | string;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string }[];
}

export interface ChainFilterDef {
  id: string;
  label: string;
  description: string;
  params: ChainFilterParam[];
}

/** Color preset choices come from the editor's filter categories (minus "none"). */
export const COLOR_FILTER_OPTIONS = FILTER_CATEGORIES
  .flatMap(cat => cat.filters)
  .filter(f => f.id !== 'none')
  .map(f => ({ value: f.id, label: f.label }));

/**
 * The chain's built-in filter registry (MVP set — mirrors the editor's simple
 * half; heavy creative effects are deliberately deferred).
 */
export const CHAIN_FILTER_DEFS: ChainFilterDef[] = [
  {
    id: 'color-filter',
    label: 'Color Filter',
    description: 'Apply a color preset (film, B&W, …)',
    params: [
      { name: 'filter', label: 'Filter', type: 'enum', default: 'chrome', options: COLOR_FILTER_OPTIONS },
    ],
  },
  {
    id: 'color-grade',
    label: 'Color Grade',
    description: 'Temp, contrast, saturation…',
    params: [
      { name: 'temperature', label: 'Temperature', type: 'number', default: 0, min: -100, max: 100, step: 1 },
      { name: 'brightness', label: 'Brightness', type: 'number', default: 0, min: -100, max: 100, step: 1 },
      { name: 'contrast', label: 'Contrast', type: 'number', default: 0, min: -100, max: 100, step: 1 },
      { name: 'saturation', label: 'Saturation', type: 'number', default: 0, min: -100, max: 100, step: 1 },
      { name: 'exposure', label: 'Exposure', type: 'number', default: 0, min: -100, max: 100, step: 1 },
      { name: 'gamma', label: 'Gamma', type: 'number', default: 1, min: 0.2, max: 2.2, step: 0.05 },
    ],
  },
  {
    id: 'sharpen',
    label: 'Sharpen',
    description: 'Unsharp mask',
    params: [
      { name: 'amount', label: 'Amount', type: 'number', default: 30, min: 0, max: 100, step: 1 },
    ],
  },
  {
    id: 'blur',
    label: 'Blur',
    description: 'Gaussian blur',
    params: [
      { name: 'amount', label: 'Amount', type: 'number', default: 20, min: 0, max: 100, step: 1 },
    ],
  },
  {
    id: 'clarity',
    label: 'Clarity',
    description: 'Local contrast boost',
    params: [
      { name: 'amount', label: 'Amount', type: 'number', default: 30, min: 0, max: 100, step: 1 },
    ],
  },
  {
    id: 'vignette',
    label: 'Vignette',
    description: 'Darkened corners',
    params: [
      { name: 'amount', label: 'Amount', type: 'number', default: 40, min: 0, max: 100, step: 1 },
    ],
  },
  {
    id: 'crop',
    label: 'Crop / Aspect',
    description: 'Center-crop to a ratio',
    params: [
      {
        name: 'aspect', label: 'Aspect', type: 'enum', default: '1:1',
        options: [
          { value: '1:1', label: '1:1' },
          { value: '16:9', label: '16:9' },
          { value: '9:16', label: '9:16' },
          { value: '4:3', label: '4:3' },
          { value: '3:4', label: '3:4' },
          { value: '3:2', label: '3:2' },
          { value: '2:3', label: '2:3' },
        ],
      },
    ],
  },
  {
    id: 'resize',
    label: 'Resize',
    description: 'Scale to a target long edge',
    params: [
      { name: 'long_edge', label: 'Long Edge (px)', type: 'integer', default: 2048, min: 64, max: 8192, step: 64 },
    ],
  },
];

export function getChainFilterDef(filterId: string): ChainFilterDef | undefined {
  return CHAIN_FILTER_DEFS.find(f => f.id === filterId);
}

export function getChainFilterDefaults(filterId: string): Record<string, number | string> {
  const def = getChainFilterDef(filterId);
  const out: Record<string, number | string> = {};
  for (const p of def?.params ?? []) out[p.name] = p.default;
  return out;
}

export { FILTER_MATRICES };
