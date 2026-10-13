import { migrateDebugScopedStorage } from '../../src/utils/debugPrefixMigration'
import { getBlob, putBlob, listBlobKeys } from '../../src/utils/blobStorage'
Object.assign(window, { storageMigration: { migrateDebugScopedStorage, getBlob, putBlob, listBlobKeys } })
