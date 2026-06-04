import type { StimmaPlugin } from '@/types/plugins';
import EffectsControls from './EffectsControls.vue';
import { icons } from '@/components/icons';

export const effectsPlugin: StimmaPlugin = {
  id: 'effects',
  label: 'Effects',
  icon: icons.sparkles,
  controls: EffectsControls,

  setup(_editor) {
    return {};
  },
};

export { EffectsControls };
