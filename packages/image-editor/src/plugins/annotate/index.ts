import type { StimmaPlugin } from '@/types/plugins';
import AnnotateControls from './AnnotateControls.vue';
import { icons } from '@/components/icons';

export const annotatePlugin: StimmaPlugin = {
  id: 'annotate',
  label: 'Annotate',
  icon: icons.pencil,
  controls: AnnotateControls,
  setup: () => ({}),
};
