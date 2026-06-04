import type { StimmaPlugin } from '@/types/plugins';
import FilterControls from './FilterControls.vue';
import { icons } from '@/components/icons';

export const filterPlugin: StimmaPlugin = {
  id: 'filter',
  label: 'Filters',
  icon: icons.filter,
  controls: FilterControls,
  setup: () => ({}),
};
