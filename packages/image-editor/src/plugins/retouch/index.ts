import type { StimmaPlugin } from '@/types/plugins';
import RetouchControls from './RetouchControls.vue';
import RetouchOverlay from './RetouchOverlay.vue';
import { icons } from '@/components/icons';

export const retouchPlugin: StimmaPlugin = {
  id: 'retouch',
  label: 'Retouch',
  icon: icons.retouch,
  controls: RetouchControls,
  overlay: RetouchOverlay,
  setup: () => ({}),
};
