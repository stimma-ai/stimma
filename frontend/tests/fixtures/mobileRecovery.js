import '../../src/apiConfig.js'
import axios from 'axios'
import { mobileRecoveryVisible, setMobileSocketReady } from '../../src/composables/useMobileRecovery.js'
window.recovery = { visible: mobileRecoveryVisible, setMobileSocketReady, axios }
