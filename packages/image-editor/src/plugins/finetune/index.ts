import type { StimmaPlugin } from '@/types/plugins';
import FinetuneControls from './FinetuneControls.vue';
import { icons } from '@/components/icons';

export const finetunePlugin: StimmaPlugin = {
  id: 'finetune',
  label: 'Levels',
  icon: icons.sliders,
  controls: FinetuneControls,

  setup(_editor) {
    return {};
  },
};

export { FinetuneControls };
