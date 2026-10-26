import '../../src/apiConfig.js'
import axios from 'axios'
import { mobileRecoveryStatus, mobileRecoveryVisible, setMobileSocketReady } from '../../src/composables/useMobileRecovery.js'
import { fetchCloudAccount } from '../../src/composables/useCloudAccount.js'
window.recovery = { visible: mobileRecoveryVisible, status: mobileRecoveryStatus, setMobileSocketReady, axios, fetchCloudAccount }
