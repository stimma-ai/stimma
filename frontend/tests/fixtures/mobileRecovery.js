import '../../src/apiConfig.js'
import axios from 'axios'
import { mobilePageChanged, mobileRecoveryStatus, mobileRecoveryVisible, setMobileSocketReady } from '../../src/composables/useMobileRecovery.js'
import { fetchCloudAccount } from '../../src/composables/useCloudAccount.js'
window.recovery = { visible: mobileRecoveryVisible, status: mobileRecoveryStatus, setMobileSocketReady, pageChanged: mobilePageChanged, axios, fetchCloudAccount }
