import { createApp, h } from 'vue'
import '../../src/style.css'
import SpritePlayer from '../../src/components/viewers/SpritePlayer.vue'

createApp({
  render: () => h(SpritePlayer, { mediaId: 1, overlay: true, autoplay: false }),
}).mount('#app')
