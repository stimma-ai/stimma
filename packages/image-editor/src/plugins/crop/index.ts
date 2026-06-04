import type { StimmaPlugin } from '@/types/plugins';
import CropControls from './CropControls.vue';
import { icons } from '@/components/icons';

export const cropPlugin: StimmaPlugin = {
  id: 'crop',
  label: 'Crop',
  icon: icons.crop,
  controls: CropControls,

  setup(_editor) {
    return {};
  },
};

export { CropControls };
